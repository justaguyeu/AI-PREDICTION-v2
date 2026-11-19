"""Prediction generation end to end with a synthetic fitted model (offline)."""
import unittest
from unittest import mock


from engine import model as M
from tests.helpers import fitted_model


def predict(odds=None, use_model=True, history=True, home="Team 00", away="Team 05"):
    model, df, _, _ = fitted_model()
    if not use_model:
        return M.predict_with_model(None, None, None, home, away, "Football / Test / League", odds)
    return M.predict_with_model(model, home, away, home, away, "Football / England / Premier League", odds,
                                history=df if history else None)


class Sources(unittest.TestCase):
    def test_all_four_sources(self):
        self.assertEqual(predict([2.0, 3.4, 3.8])["analysis_meta"]["data_source"], "model+market")
        self.assertEqual(predict([2.0, 3.4, 3.8], use_model=False)["analysis_meta"]["data_source"], "market")
        self.assertEqual(predict(None)["analysis_meta"]["data_source"], "model")
        self.assertEqual(predict(None, use_model=False)["analysis_meta"]["data_source"], "none")


class ProbabilityConsistency(unittest.TestCase):
    def test_probabilities_sum_and_match_markets(self):
        for odds in ([2.0, 3.4, 3.8], [1.25, 6.0, 11.0], None):
            p = predict(odds)
            pr = p["probabilities"]
            self.assertAlmostEqual(pr["home"] + pr["draw"] + pr["away"], 100, delta=0.2)
            o = p["markets"]["1x2_ft"]["options"]
            self.assertAlmostEqual(pr["home"], o["1"], delta=0.11)
            self.assertAlmostEqual(pr["draw"], o["X"], delta=0.11)
            for v in (pr["home"], pr["draw"], pr["away"]):
                self.assertTrue(0 <= v <= 100)
            names = {"HOME WIN": "home", "DRAW": "draw", "AWAY WIN": "away"}
            self.assertEqual(pr[names[pr["most_likely"]]], max(pr["home"], pr["draw"], pr["away"]))

    def test_blend_sits_between_model_and_market(self):
        p = predict([1.5, 4.2, 6.5])
        mo, mk = p["analysis_meta"]["model_1x2"], p["analysis_meta"]["market_1x2"]
        lo, hi = sorted((mo["1"], mk["1"]))
        self.assertTrue(lo - 0.5 <= p["probabilities"]["home"] <= hi + 0.5)

    def test_goals_block_matches_markets(self):
        p = predict([2.0, 3.4, 3.8])
        self.assertEqual(p["goals"]["btts_yes"], p["markets"]["btts"]["options"]["YES"])
        self.assertGreater(p["goals"]["over_1_5"], p["goals"]["over_2_5"])
        self.assertGreater(p["goals"]["over_2_5"], p["goals"]["over_3_5"])


class Assessment(unittest.TestCase):
    def test_no_data_means_no_false_precision(self):
        p = predict(None, use_model=False)
        self.assertEqual(p["assessment"]["data_quality"]["level"], "INSUFFICIENT")
        self.assertEqual(p["assessment"]["model_confidence"]["level"], "INSUFFICIENT")
        self.assertIsNone(p["safest_pick"])
        self.assertEqual(p["best_bet"]["pick"], "")
        self.assertFalse(p["probabilities"]["high_confidence"])
        self.assertNotIn("hit_rate", p["markets"]["1x2_ft"])

    def test_invalid_odds_are_rejected_and_reported(self):
        p = predict([5.0, 6.0, 7.0])                   # implied total 51%: impossible
        self.assertEqual(p["analysis_meta"]["data_source"], "model")
        self.assertTrue(any("rejected" in r for r in p["risks"]))
        self.assertIsNone(p["value"])

    def test_team_with_too_few_matches_is_not_rated(self):
        model, df, _, _ = fitted_model()
        saved = model.recent["Team 05"]
        model.recent["Team 05"] = M.MIN_TEAM_MATCHES - 1
        try:
            p = predict([2.0, 3.4, 3.8])
        finally:
            model.recent["Team 05"] = saved
        self.assertEqual(p["analysis_meta"]["data_source"], "market")
        self.assertTrue(any("fewer than" in r for r in p["risks"]))

    def test_disagreement_lowers_model_confidence(self):
        p = predict([1.3, 5.5, 9.0])
        gap = max(abs(p["analysis_meta"]["model_1x2"][k] - p["analysis_meta"]["market_1x2"][k]) for k in "1X2")
        level = p["assessment"]["model_confidence"]["level"]
        if gap > 15:
            self.assertEqual(level, "LOW")

    def test_risks_always_mention_team_news(self):
        p = predict([2.0, 3.4, 3.8])
        self.assertTrue(any("Injuries" in r for r in p["risks"]))
        self.assertTrue(p["factors"])


class Value(unittest.TestCase):
    def test_expected_value_formula(self):
        odds = [2.0, 3.4, 3.8]
        p = predict(odds)
        mo = p["analysis_meta"]["model_1x2"]
        for o, prob, key, odd in zip(p["value"]["outcomes"], ("home", "draw", "away"), "1X2", odds):
            self.assertAlmostEqual(o["ev"] / 100, (p["probabilities"][prob] / 100) * odd - 1, delta=0.003)
            self.assertAlmostEqual(o["ev_model"] / 100, (mo[key] / 100) * odd - 1, delta=0.003)

    def test_flags_off_by_default_and_opt_in(self):
        mo = predict(None)["analysis_meta"]["model_1x2"]
        near = [round(100 / (mo[k] * 1.05), 2) for k in "1X2"]           # odds close to the model's view
        with mock.patch.object(M, "VALUE_EV_THRESHOLD", None):
            self.assertFalse(any(o["flag"] for o in predict(near)["value"]["outcomes"]))
        with mock.patch.object(M, "VALUE_EV_THRESHOLD", -1.0):          # flag everything the model rates
            p = predict(near)
            self.assertTrue(p["value"]["eligible"])
            self.assertTrue(all(o["flag"] for o in p["value"]["outcomes"]))
            far = list(reversed(near))                                   # bookmaker sees the opposite
            self.assertEqual(predict(far)["assessment"]["model_confidence"]["level"], "LOW")
            self.assertFalse(any(o["flag"] for o in predict(far)["value"]["outcomes"]))

    def test_published_probabilities_follow_the_odds(self):
        from engine.market import MARKET_WEIGHT, implied_probs
        p = predict([2.0, 3.4, 3.8])
        if MARKET_WEIGHT == 1.0:
            fair = implied_probs([2.0, 3.4, 3.8]) * 100
            self.assertAlmostEqual(p["probabilities"]["home"], fair[0], delta=0.2)
            self.assertAlmostEqual(p["probabilities"]["draw"], fair[1], delta=0.2)

    def test_market_only_never_flags_value(self):
        p = predict([2.0, 3.4, 3.8], use_model=False)
        self.assertFalse(any(o["flag"] for o in p["value"]["outcomes"]))
        self.assertTrue(all(o["ev"] < 0 for o in p["value"]["outcomes"]))   # margin makes fair odds lose


class Context(unittest.TestCase):
    def test_context_present_with_history(self):
        p = predict([2.0, 3.4, 3.8])
        self.assertIsNotNone(p["context"])
        self.assertIn("last10", p["context"]["home_form"])
        self.assertIsNone(predict([2.0, 3.4, 3.8], history=False)["context"])

    def test_metadata(self):
        p = predict([2.0, 3.4, 3.8])
        self.assertEqual(p["model_version"], M.MODEL_VERSION)
        self.assertTrue(p["created_at"])
        self.assertTrue(p["sources"])


if __name__ == "__main__":
    unittest.main()
