"""Form, venue form, head-to-head and rest days from a small hand-made results table."""
import unittest

import numpy as np
import pandas as pd

from engine.analysis import head_to_head, match_context, rest_days, team_form, venue_form

ROWS = [  # date, home, away, hg, ag
    ("2026-09-01", "A", "B", 2, 0),
    ("2026-09-08", "C", "A", 1, 1),
    ("2026-09-15", "A", "C", 0, 1),
    ("2026-09-22", "B", "A", 3, 3),
    ("2026-09-29", "A", "B", 1, 0),
    ("2026-10-06", "B", "C", 2, 2),
]
DF = pd.DataFrame([{"date": pd.Timestamp(d), "home": h, "away": a, "hg": hg, "ag": ag, "league": "E0",
                    "hxg": np.nan, "axg": np.nan, "hst": np.nan, "ast": np.nan} for d, h, a, hg, ag in ROWS])
BEFORE = pd.Timestamp("2026-10-10")


class Form(unittest.TestCase):
    def test_last5_for_team_a(self):
        f = team_form(DF, "A", BEFORE)["last5"]
        self.assertEqual(f["matches"], 5)
        self.assertEqual(f["sequence"], "WDLDW")          # most recent first: 1-0 W, 3-3 D, 0-1 L, 1-1 D, 2-0 W
        self.assertEqual((f["w"], f["d"], f["l"]), (2, 2, 1))
        self.assertEqual((f["gf"], f["ga"]), (7, 5))
        self.assertAlmostEqual(f["ppg"], 8 / 5, places=2)
        self.assertEqual(f["clean_sheets"], 2)
        self.assertEqual(f["failed_to_score"], 1)
        self.assertNotIn("xg_for", f)                     # no xG in the data -> not reported

    def test_no_future_results(self):
        f = team_form(DF, "A", pd.Timestamp("2026-09-20"))["last5"]
        self.assertEqual(f["matches"], 3)

    def test_venue_form(self):
        home = venue_form(DF, "A", "home", BEFORE)
        self.assertEqual((home["matches"], home["w"], home["l"]), (3, 2, 1))
        away = venue_form(DF, "A", "away", BEFORE)
        self.assertEqual((away["matches"], away["d"]), (2, 2))

    def test_unknown_team(self):
        self.assertIsNone(team_form(DF, "Z", BEFORE)["last5"])


class HeadToHead(unittest.TestCase):
    def test_counts_from_fixture_home_view(self):
        h = head_to_head(DF, "B", "A", BEFORE)            # B at home vs A
        self.assertEqual(len(h["meetings"]), 3)
        self.assertEqual((h["home_wins"], h["draws"], h["away_wins"]), (0, 1, 2))
        self.assertEqual(h["meetings"][0]["score"], "1-0")   # most recent first


class Rest(unittest.TestCase):
    def test_rest_days(self):
        self.assertEqual(rest_days(DF, "C", BEFORE), 4)
        self.assertIsNone(rest_days(DF, "Z", BEFORE))

    def test_cup_and_european_matches_shorten_rest(self):
        other = pd.DataFrame([{"date": pd.Timestamp("2026-10-08"), "team": "A", "opponent": "Z",
                               "competition": "uefa.champions", "slug": "uefa.champions"}])
        self.assertEqual(rest_days(DF, "A", BEFORE), 11)                 # league only: 29 Sep
        self.assertEqual(rest_days(DF, "A", BEFORE, other), 2)           # Champions League on 8 Oct
        c = match_context(DF, "A", "B", before=BEFORE, other=other)
        self.assertEqual(c["last_match"]["home"]["competition"], "uefa.champions")
        self.assertEqual(c["rest_scope"], "league, cup and continental matches")

    def test_context_bundle(self):
        c = match_context(DF, "A", "B", before=BEFORE)
        self.assertEqual(c["data_through"], "2026-10-06")
        self.assertIn("cups", c["scope"])
        self.assertEqual(c["rest_days"], {"home": 11, "away": 4})


if __name__ == "__main__":
    unittest.main()
