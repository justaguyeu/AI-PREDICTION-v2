"""
Live data-source checks. Skipped unless RUN_NETWORK_TESTS=1, because they download from
football-data.co.uk and ESPN (and write to the data/cache and data/results caches).

    set RUN_NETWORK_TESTS=1 && python -m unittest tests.test_network     (Windows cmd)
"""
import datetime
import os
import unittest

RUN = os.environ.get("RUN_NETWORK_TESTS") == "1"


@unittest.skipUnless(RUN, "set RUN_NETWORK_TESTS=1 to run live data-source checks")
class LiveSources(unittest.TestCase):
    def test_football_data(self):
        from engine.data import load_league
        df = load_league("E0")
        self.assertGreater(len(df), 300)
        for col in ("date", "home", "away", "hg", "ag", "oh", "od", "oa"):
            self.assertIn(col, df.columns)
        self.assertGreater(df["date"].max(), datetime.datetime.now() - datetime.timedelta(days=120))

    def test_espn(self):
        from engine.results import espn_results
        d = datetime.date.today() - datetime.timedelta(days=7)
        df = espn_results(d, d + datetime.timedelta(days=2))
        self.assertGreater(len(df), 0)
        self.assertTrue(((df["hg"] >= 0) & (df["ag"] >= 0)).all())

    def test_prediction_for_a_real_league(self):
        from engine.model import predict_match
        p = predict_match("Arsenal FC", "Chelsea FC", "Football / England / Premier League", [1.9, 3.6, 4.2])
        self.assertEqual(p["analysis_meta"]["data_source"], "model+market")
        self.assertIsNotNone(p["context"])


if __name__ == "__main__":
    unittest.main()
