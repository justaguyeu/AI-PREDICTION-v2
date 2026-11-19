"""Probability maths: score matrix, odds, blending, market derivation, model fitting, calibration."""
import math
import unittest

import numpy as np
from scipy.stats import poisson

from engine import calibration, dixon_coles as dc
from engine.market import blend, implied_probs, outcome_probs, rates_from_1x2, valid_overround
from engine.model import draw_risk
from engine.poisson import all_markets
from tests.helpers import TRUE_HOME_ADV, fitted_model


def pct(x):
    return float(str(x).rstrip("%"))


class ScoreMatrix(unittest.TestCase):
    def test_is_a_distribution(self):
        for lam, mu, rho in [(1.4, 1.1, -0.05), (0.3, 3.0, 0.1), (2.5, 0.4, -0.2)]:
            m = dc.score_matrix(lam, mu, rho)
            self.assertTrue((m >= 0).all())
            self.assertAlmostEqual(m.sum(), 1.0, places=9)

    def test_rho_zero_is_independent_poisson(self):
        m = dc.score_matrix(1.3, 0.9, 0.0)
        k = np.arange(m.shape[0])
        expected = np.outer(poisson.pmf(k, 1.3), poisson.pmf(k, 0.9))
        np.testing.assert_allclose(m, expected / expected.sum(), atol=1e-12)

    def test_negative_rho_raises_draws_at_low_scores(self):
        self.assertGreater(dc.score_matrix(1.2, 1.0, -0.1)[0, 0], dc.score_matrix(1.2, 1.0, 0.0)[0, 0])

    def test_outcome_probs_sum_to_one(self):
        p = outcome_probs(dc.score_matrix(1.6, 1.0, -0.05))
        self.assertAlmostEqual(p.sum(), 1.0, places=9)
        self.assertGreater(p[0], p[2])


class Odds(unittest.TestCase):
    def test_margin_removed_and_order_kept(self):
        odds = [1.80, 3.60, 4.50]
        p = implied_probs(odds)
        self.assertAlmostEqual(p.sum(), 1.0, places=9)
        for pi, o in zip(p, odds):
            self.assertLess(pi, 1 / o)               # fair probability is below the raw implied one
        self.assertTrue(p[0] > p[1] > p[2])

    def test_power_method_takes_more_margin_from_longshots(self):
        odds = [1.30, 5.0, 10.0]
        p = implied_probs(odds)
        inv = 1 / np.array(odds)
        proportional = inv / inv.sum()
        self.assertGreater(p[0], proportional[0])
        self.assertLess(p[2], proportional[2])

    def test_invalid_odds_rejected(self):
        for bad in [None, [2.0, 3.0], [1.0, 3.0, 4.0], ["x", 3, 4], [5.0, 6.0, 7.0],   # last: margin < 0
                    [1.2, 1.5, 1.5], [float("nan"), 3, 3]]:
            self.assertIsNone(implied_probs(bad), bad)

    def test_overround_bounds(self):
        self.assertFalse(valid_overround(0.95))
        self.assertTrue(valid_overround(1.06))
        self.assertFalse(valid_overround(1.5))


class Blend(unittest.TestCase):
    def test_endpoints_and_normalisation(self):
        pm, pk = np.array([0.5, 0.3, 0.2]), np.array([0.4, 0.3, 0.3])
        np.testing.assert_allclose(blend(pm, pk, 0.0), pm, atol=1e-12)
        np.testing.assert_allclose(blend(pm, pk, 1.0), pk, atol=1e-12)
        mid = blend(pm, pk, 0.5)
        self.assertAlmostEqual(mid.sum(), 1.0, places=12)
        self.assertTrue(pk[0] < mid[0] < pm[0])

    def test_missing_side(self):
        p = np.array([0.5, 0.3, 0.2])
        np.testing.assert_allclose(blend(p, None), p)
        np.testing.assert_allclose(blend(None, p), p)


class RatesFrom1x2(unittest.TestCase):
    def test_inverts_the_score_matrix(self):
        for lam, mu, rho in [(1.5, 1.1, -0.05), (0.9, 1.7, -0.1), (2.4, 0.6, 0.0)]:
            p = outcome_probs(dc.score_matrix(lam, mu, rho))
            l2, m2 = rates_from_1x2(p, rho)
            self.assertAlmostEqual(l2, lam, delta=0.02)
            self.assertAlmostEqual(m2, mu, delta=0.02)


class MarketsConsistency(unittest.TestCase):
    """Every market must be read off the same score matrix, so they cannot contradict each other."""

    def setUp(self):
        self.lam, self.mu, self.rho = 1.55, 1.05, -0.06
        self.m, self.scores, self.meta = all_markets(self.lam, self.mu, self.rho, "H", "A")
        self.M = dc.score_matrix(self.lam, self.mu, self.rho)

    def test_1x2_sums_to_100_and_matches_matrix(self):
        o = self.m["1x2_ft"]["options"]
        self.assertAlmostEqual(o["1"] + o["X"] + o["2"], 100, delta=0.2)
        p = outcome_probs(self.M) * 100
        self.assertAlmostEqual(o["1"], p[0], delta=0.06)
        self.assertAlmostEqual(o["X"], p[1], delta=0.06)

    def test_double_chance_is_sum_of_1x2(self):
        o, dc_ = self.m["1x2_ft"]["options"], self.m["double_chance"]["options"]
        self.assertAlmostEqual(dc_["1X"], o["1"] + o["X"], delta=0.15)
        self.assertAlmostEqual(dc_["X2"], o["X"] + o["2"], delta=0.15)
        self.assertAlmostEqual(dc_["12"], o["1"] + o["2"], delta=0.15)

    def test_btts_and_handicap_sum_to_100(self):
        b = self.m["btts"]["options"]
        self.assertAlmostEqual(b["YES"] + b["NO"], 100, delta=0.15)
        self.assertAlmostEqual(sum(self.m["handicap"]["options"].values()), 100, delta=0.2)

    def test_over_probabilities_fall_with_the_line(self):
        overs = [t["over"] for t in self.m["ou_ft"]["all_thresholds"]]
        self.assertEqual(overs, sorted(overs, reverse=True))
        tot = np.add.outer(np.arange(self.M.shape[0]), np.arange(self.M.shape[1]))
        self.assertAlmostEqual(overs[2], self.M[tot > 2.5].sum() * 100, delta=0.06)

    def test_btts_matches_matrix(self):
        self.assertAlmostEqual(self.m["btts"]["options"]["YES"], self.M[1:, 1:].sum() * 100, delta=0.06)

    def test_correct_scores_sorted_and_plausible(self):
        probs = [s["prob"] for s in self.scores]
        self.assertEqual(probs, sorted(probs, reverse=True))
        self.assertAlmostEqual(probs[0], self.M.max() * 100, delta=0.01)

    def test_picks_are_the_more_likely_side(self):
        self.assertEqual(self.m["1x2_ft"]["prediction"], "HOME WIN")
        o = self.m["btts"]["options"]
        self.assertEqual(self.m["btts"]["prediction"], "YES" if o["YES"] > o["NO"] else "NO")
        self.assertGreaterEqual(pct(self.m["ou_ft"]["confidence"]), 50)

    def test_first_half_has_fewer_goals(self):
        self.assertGreater(self.m["ou_h1"]["all_thresholds"][0]["confidence"], 0)
        h1_over05 = [t for t in self.m["ou_h1"]["all_thresholds"] if t["label"].endswith("0.5")][0]["over"]
        ft_over05 = [t for t in self.m["ou_ft"]["all_thresholds"] if t["label"].endswith("0.5")][0]["over"]
        self.assertLess(h1_over05, ft_over05)


class DixonColesFit(unittest.TestCase):
    def test_recovers_known_strengths(self):
        model, df, att, dfn = fitted_model()
        teams = sorted(att)
        true_strength = [att[t] - dfn[t] for t in teams]
        fit_strength = [model.attack[t] - model.defence[t] for t in teams]
        self.assertGreater(np.corrcoef(true_strength, fit_strength)[0, 1], 0.85)
        self.assertAlmostEqual(model.home_adv, TRUE_HOME_ADV, delta=0.12)

    def test_no_future_data_used(self):
        model, df, _, _ = fitted_model()
        cutoff = df["date"].iloc[len(df) // 2]
        early = dc.fit(df, ref_date=cutoff)
        late_only_teams = set(df[df["date"] >= cutoff]["home"]) - set(df[df["date"] < cutoff]["home"])
        self.assertTrue(late_only_teams.isdisjoint(early.teams))
        changed = df.copy()
        changed.loc[changed["date"] >= cutoff, "hg"] = 9          # rewrite the future
        again = dc.fit(changed, ref_date=cutoff)
        self.assertAlmostEqual(early.home_adv, again.home_adv, places=9)

    def test_xg_weight_without_xg_changes_nothing(self):
        _, df, _, _ = fitted_model()
        a = dc.fit(df, xg_weight=0.0)
        b = dc.fit(df, xg_weight=0.5)                             # synthetic data has no xG
        self.assertAlmostEqual(a.home_adv, b.home_adv, places=9)

    def test_too_little_data(self):
        _, df, _, _ = fitted_model()
        self.assertIsNone(dc.fit(df.head(10)))


class Calibration(unittest.TestCase):
    def test_build_is_monotonic_and_bounded(self):
        import pandas as pd
        rng = np.random.default_rng(3)
        p = rng.uniform(0.35, 0.95, 4000)
        hit = rng.uniform(size=4000) < (p - 0.03)                # truth slightly below the stated prob
        cal = calibration.build(pd.DataFrame({"market": "X", "prob": p, "hit": hit}))["X"]
        self.assertEqual(cal["y"], sorted(cal["y"]))
        self.assertTrue(all(0 <= y <= 1 for y in cal["y"]))
        self.assertLess(np.mean(cal["y"]), np.mean(cal["x"]))      # learned the over-confidence

    def test_unknown_market_returns_raw_probability(self):
        self.assertEqual(calibration.hit_rate("no such market", 0.42), 0.42)


class DrawRisk(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(draw_risk(0.22)["level"], "LOW")
        self.assertEqual(draw_risk(0.28)["level"], "MEDIUM")
        self.assertEqual(draw_risk(0.31)["level"], "HIGH")


if __name__ == "__main__":
    unittest.main()
