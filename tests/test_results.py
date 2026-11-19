"""Which ESPN matches count as a team's recent cup/continental games (offline, synthetic feed)."""
import unittest
from unittest import mock

import pandas as pd

from engine import results

FEED = pd.DataFrame([
    # date, home, away, slug, status
    ("2026-10-20", "Paris Saint-Germain", "Barcelona", "uefa.champions", "ft"),     # counts for Barcelona
    ("2026-10-21", "Espanyol", "Real Zaragoza", "esp.copa_del_rey", "pen"),         # cup tie on penalties: counts
    ("2026-10-21", "Barcelona SC", "Emelec", "ecu.1", "ft"),                        # Ecuador: never Spain's Barcelona
    ("2026-10-22", "Barcelona", "Sevilla", "esp.1", "ft"),                          # league: already in league data
    ("2026-10-22", "Barcelona", "Real Madrid", "esp.w.1", "ft"),                    # women's league
], columns=["date", "home", "away", "slug", "status"]).assign(
    date=lambda d: pd.to_datetime(d["date"]), hg=1, ag=0, competition="x",
    league=lambda d: d["slug"].map(results.ESPN_TO_FD))


class OtherMatches(unittest.TestCase):
    def test_filter_by_country_and_competition(self):
        with mock.patch.object(results, "espn_results", lambda a, b, include_extra_time=False: FEED):
            df = results.recent_other_matches("spain", ["Barcelona", "Espanol", "Sevilla", "Real Madrid"])
        got = sorted(zip(df["team"], df["slug"]))
        self.assertEqual(got, [("Barcelona", "uefa.champions"), ("Espanol", "esp.copa_del_rey")])

    def test_unknown_country(self):
        self.assertTrue(results.recent_other_matches("atlantis", ["X"]).empty)

    def test_grading_feed_excludes_extra_time(self):
        rows = [{"date": "2026-10-21", "home": "A", "away": "B", "hg": 1, "ag": 1, "competition": "c",
                 "slug": "s", "status": "pen"},
                {"date": "2026-10-21", "home": "C", "away": "D", "hg": 2, "ag": 0, "competition": "c",
                 "slug": "s", "status": "ft"},
                {"date": "2026-10-21", "home": "E", "away": "F", "hg": 0, "ag": 0, "competition": "c",
                 "slug": "s"}]                                                # old cache rows: no status
        with mock.patch.object(results, "_day", lambda d: rows):
            day = pd.Timestamp("2026-10-21").date()
            self.assertEqual(sorted(results.espn_results(day, day)["home"]), ["C", "E"])
            self.assertEqual(len(results.espn_results(day, day, include_extra_time=True)), 3)


if __name__ == "__main__":
    unittest.main()
