"""Storage safety, result grading and the Flask API (all in a temporary folder; never touches data/)."""
import json
import os
import tempfile
import unittest
from unittest import mock

import pandas as pd

from engine import storage
from tests.test_model import predict


class Storage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = mock.patch.object(storage, "STORAGE_DIR", self.tmp.name)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_save_and_get(self):
        storage.save_prediction("A", "B", {"status": "success", "x": 1})
        self.assertEqual(storage.get_prediction("A", "B")["x"], 1)
        self.assertTrue(storage.get_prediction("A", "B")["saved_at"])

    def test_first_prediction_is_kept(self):
        storage.save_prediction("A", "B", {"status": "success", "x": 1})
        kept = storage.save_prediction("A", "B", {"status": "success", "x": 2})
        self.assertEqual(kept["x"], 1)
        self.assertEqual(storage.get_prediction("A", "B")["x"], 1)

    def test_new_engine_version_keeps_the_old_prediction(self):
        path = storage.get_storage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"A_vs_B": {"status": "success", "engine": "dc-v1", "x": "old"}}, f)
        storage.save_prediction("A", "B", {"status": "success", "x": "new"})
        data = storage.load_all_predictions()
        self.assertEqual(data["A_vs_B"]["x"], "new")
        self.assertEqual(data["A_vs_B@dc-v1"]["x"], "old")

    def test_other_matches_survive(self):
        storage.save_prediction("A", "B", {"status": "success"})
        storage.save_prediction("C", "D", {"status": "success"})
        self.assertEqual(set(storage.load_all_predictions()), {"A_vs_B", "C_vs_D"})

    def test_unreadable_file_is_moved_aside_not_overwritten(self):
        path = storage.get_storage_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write('{"half written": ')
        storage.save_prediction("A", "B", {"status": "success"})
        aside = [n for n in os.listdir(self.tmp.name) if ".unreadable-" in n]
        self.assertEqual(len(aside), 1)
        with open(os.path.join(self.tmp.name, aside[0]), encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"half written": ')
        self.assertEqual(set(storage.load_all_predictions()), {"A_vs_B"})

    def test_no_temp_files_left(self):
        storage.save_prediction("A", "B", {"status": "success"})
        self.assertEqual([n for n in os.listdir(self.tmp.name) if ".tmp-" in n], [])


class Grading(unittest.TestCase):
    def test_grade_all_markets(self):
        import review
        p = predict([1.8, 3.6, 4.6])
        g = {x["market"]: x for x in review.grade(p, 2, 1, 1, 0)}
        self.assertEqual(g["1X2"]["hit"], p["markets"]["1x2_ft"]["prediction"] == "HOME WIN")
        self.assertEqual(g["BTTS"]["hit"], p["markets"]["btts"]["prediction"] == "YES")
        self.assertEqual(g["O/U 2.5"]["hit"], g["O/U 2.5"]["pick"].startswith("OVER"))
        self.assertEqual(g["Handicap -1"]["hit"], p["markets"]["handicap"]["prediction"] == "X (-1)")
        self.assertEqual(g["Correct score"]["hit"], p["correct_scores"][0]["score"] == "2 - 1")
        self.assertIn("HT/FT", g)

    def test_kickoff_window(self):
        import review
        lo, hi = review._date_window({"kickoff": "8:45 pm Tue 13/10"}, pd.Timestamp("2026-10-13"))
        self.assertEqual((lo.date().isoformat(), hi.date().isoformat()), ("2026-10-12", "2026-10-14"))
        lo, hi = review._date_window({"kickoff": "3:00 pm Sat 03/01"}, pd.Timestamp("2026-12-30"))
        self.assertEqual(lo.year, 2027)                    # January fixture predicted in December


class ManualResults(unittest.TestCase):
    def setUp(self):
        import review
        self.review = review
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "manual_results.csv")
        empty_espn = pd.DataFrame(columns=["date", "home", "away", "hg", "ag", "competition", "slug", "league"])
        self.patches = [mock.patch.object(review, "MANUAL_RESULTS", self.path),
                        mock.patch.object(review, "espn_results", lambda a, b: empty_espn)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_template_then_typed_score_is_used(self):
        pred = {"home": "Al Zawraa", "away": "Al Shorta SC", "league": "Football / Iraq / Iraqi League",
                "kickoff": "5:00 pm Fri 23/10", "analysis_meta": {}}
        day = pd.Timestamp("2026-10-23")
        self.assertEqual(self.review.add_to_manual_results(day, [pred]), 1)
        self.assertEqual(self.review.add_to_manual_results(day, [pred]), 0)          # no duplicates
        finder = self.review.ResultFinder(day, day)
        self.assertEqual(finder.find(pred, day), (None, None))                    # scores still empty
        with open(self.path, encoding="utf-8") as f:
            text = f.read()
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text.replace("Al Shorta SC,,", "Al Shorta SC,0,2"))
        result, src = self.review.ResultFinder(day, day).find(pred, day)
        self.assertEqual((src, result["hg"], result["ag"]), ("manual", 0, 2))


class Api(unittest.TestCase):
    def setUp(self):
        import app
        self.app = app
        self.client = app.app.test_client()
        self.stored = {}
        self.patches = [
            mock.patch.object(app, "get_prediction", lambda h, a: None),
            mock.patch.object(app, "save_prediction", lambda h, a, p: {**p, "engine": app.MODEL_VERSION}),
            mock.patch.object(app, "load_all_predictions", lambda: self.stored),
            mock.patch.object(app, "predict_match", lambda h, a, league=None, odds=None: predict(odds)),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["model_version"], self.app.MODEL_VERSION)

    def test_validation(self):
        bad = [{}, {"home": "A"}, {"home": "A", "away": "B", "odds": [2, 3]},
               {"home": "A", "away": "B", "odds": ["x", 3, 4]}, {"home": "A", "away": "B", "odds": [0.5, 3, 4]},
               {"home": "A", "away": "B", "league": 5}]
        for body in bad:
            self.assertEqual(self.client.post("/api/predict", json=body).status_code, 400, body)

    def test_predict(self):
        r = self.client.post("/api/predict", json={"home": "Team 00", "away": "Team 05",
                                                   "odds": [2.0, 3.4, 3.8], "kickoff": "8:45 pm Tue 13/10"})
        self.assertEqual(r.status_code, 200)
        d = r.get_json()
        self.assertEqual(d["kickoff"], "8:45 pm Tue 13/10")
        self.assertIn("assessment", d)

    def test_best_bets_skip_no_data(self):
        good = {**predict([2.0, 3.4, 3.8]), "engine": self.app.MODEL_VERSION}
        none = {**predict(None, use_model=False), "engine": self.app.MODEL_VERSION}
        old = {**predict([2.0, 3.4, 3.8]), "engine": "old-version"}
        self.stored.update({"g": good, "n": none, "o": old})
        bets = self.client.get("/api/best-bets").get_json()["best_bets"]
        self.assertEqual(len(bets), 1)
        self.assertEqual(bets[0]["pick"], good["safest_pick"]["pick"])


if __name__ == "__main__":
    unittest.main()
