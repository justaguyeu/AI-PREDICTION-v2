"""League resolution, team-name matching and BetPawa page parsing (regression cases from real mistakes)."""
import os
import unittest

from engine.betpawa import parse_page_text
from engine.data import match_team, resolve_league

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ResolveLeague(unittest.TestCase):
    def test_exact_names(self):
        self.assertEqual(resolve_league("Football / England / Premier League"), (["E0"], True))
        self.assertEqual(resolve_league("Football / Germany / 2. Bundesliga"), (["D2"], True))
        self.assertEqual(resolve_league("Football / Austria / Bundesliga"), (["AUT"], True))
        self.assertEqual(resolve_league("Football / Mexico / Liga MX, Apertura"), (["MEX"], True))
        self.assertEqual(resolve_league("Football / Switzerland / Super League"), (["SWZ"], True))

    def test_similar_names_do_not_match_by_substring(self):
        codes, exact = resolve_league("Football / England / Northern Premier League, Premier Division")
        self.assertFalse(exact)                       # used to resolve to the Premier League
        codes, exact = resolve_league("Football / England / National League South")
        self.assertFalse(exact)

    def test_uncovered_and_excluded(self):
        self.assertEqual(resolve_league("Football / Egypt / Premier League"), ([], False))
        self.assertEqual(resolve_league("Football / England / Premier League Women"), ([], False))
        self.assertEqual(resolve_league(None), ([], False))

    def test_cup_falls_back_to_country(self):
        codes, exact = resolve_league("Football / England / FA Cup")
        self.assertFalse(exact)
        self.assertIn("E0", codes)


class MatchTeam(unittest.TestCase):
    def test_regressions(self):
        cases = [
            ("Grasshopper Club Zurich", ["Zurich", "Grasshoppers", "Basel"], "Grasshoppers"),
            ("Manchester United", ["Man City", "Man United"], "Man United"),
            ("Heart of Midlothian", ["Hearts", "Hibernian"], "Hearts"),
            ("Dundee FC", ["Dundee", "Dundee United"], "Dundee"),
            ("Dundee United", ["Dundee", "Dundee United"], "Dundee United"),
            ("RC Celta Fortuna", ["Celta", "Celta B"], "Celta B"),
            ("Borussia Monchengladbach", ["Dortmund", "M'gladbach"], "M'gladbach"),
            ("FC Basel 1893", ["Basel", "Lugano"], "Basel"),
        ]
        for name, candidates, expected in cases:
            self.assertEqual(match_team(name, candidates)[0], expected, name)

    def test_youth_reserve_and_women_never_match_senior_teams(self):
        for name in ("Ipswich Town U21", "St Mirren B U21", "Arsenal Women", "Chelsea (W)", "Bayern Munich II"):
            self.assertIsNone(match_team(name, ["Ipswich", "St Mirren", "Arsenal", "Chelsea", "Bayern Munich"])[0],
                              name)

    def test_unknown_team(self):
        self.assertIsNone(match_team("Al Hilal SFC", ["Arsenal", "Chelsea"])[0])

    def test_generic_words_alone_never_match(self):
        # 2026-10-23: "Al Zawraa v Al Shorta SC" was graded with "Al Fateh 1-3 Al Shabab"
        self.assertIsNone(match_team("Al Zawraa", ["Al Fateh", "Al Shabab"])[0])
        self.assertIsNone(match_team("Al Shorta SC", ["Al Fateh", "Al Shabab"])[0])
        self.assertIsNone(match_team("Real Madrid", ["Real Betis", "Sevilla"])[0])
        self.assertIsNone(match_team("St Mirren", ["St Johnstone", "Hibernian"])[0])
        self.assertIsNone(match_team("Sheffield Weds", ["Sheffield United", "Leeds"])[0])
        self.assertIsNone(match_team("West Ham United", ["West Brom", "Fulham"])[0])

    def test_generic_words_still_allowed_with_a_distinctive_match(self):
        cases = [
            ("Al-Faisaly FC", ["Al Faisaly", "Al Nassr"], "Al Faisaly"),
            ("Al Hilal SFC", ["Al Hilal", "Al Ahli"], "Al Hilal"),
            ("Bristol City FC", ["Bristol City", "Bristol Rvs"], "Bristol City"),
            ("BSC Young Boys", ["Young Boys", "Basel"], "Young Boys"),
            ("Stade Brest 29", ["Brest", "Nice"], "Brest"),
            ("Nottingham Forest", ["Nott'm Forest", "Forest Green"], "Nott'm Forest"),
            ("Union Saint-Gilloise", ["St. Gilloise", "Gent"], "St. Gilloise"),
            ("Vasteraas SK", ["Vasteras SK", "Halmstad"], "Vasteras SK"),
            # abbreviations and places in brackets (ESPN names vs football-data names)
            ("Inverness Caledonian Thistle", ["Inverness C", "Ayr"], "Inverness C"),
            ("Argentinos Juniors", ["Argentinos Jrs", "Boca Juniors"], "Argentinos Jrs"),
            ("Gimnasia La Plata", ["Gimnasia L.P.", "Gimnasia Mendoza"], "Gimnasia L.P."),
            ("Gimnasia (Mendoza)", ["Gimnasia L.P.", "Gimnasia Mendoza"], "Gimnasia Mendoza"),
            ("Urawa Red Diamonds", ["Urawa Reds", "Kashima"], "Urawa Reds"),
            ("D.C. United", ["DC United", "Toronto"], "DC United"),
            ("Dinamo Moscow", ["Dynamo Moscow", "Spartak Moscow"], "Dynamo Moscow"),
        ]
        self.assertIsNone(match_team("Austria Lustenau", ["Austria Vienna", "Rapid Vienna"])[0])
        self.assertIsNone(match_team("América", ["Almeria", "Sevilla"])[0])
        self.assertIsNone(match_team("América de Cali", ["Almeria", "Sevilla"])[0])
        for name, cands, want in [("Deportivo", ["La Coruna", "Levante"], "La Coruna"),
                                  ("RC Deportivo de A Coruna", ["La Coruna", "Levante"], "La Coruna"),
                                  ("Bodoe/Glimt", ["Bodo/Glimt", "Valerenga"], "Bodo/Glimt"),
                                  ("Vaalerenga IF", ["Bodo/Glimt", "Valerenga"], "Valerenga"),
                                  ("Hamburger SV", ["Hamburg", "Bremen"], "Hamburg"),
                                  ("Krylia Sovetov", ["Krylya Sovetov", "Rostov"], "Krylya Sovetov"),
                                  ("1. FC Cologne", ["FC Koln", "Schalke 04"], "FC Koln")]:
            self.assertEqual(match_team(name, cands)[0], want, name)
        self.assertIsNone(match_team("Fukushima United FC", ["Yokohama F. Marinos", "Kashima"])[0])
        self.assertIsNone(match_team("Vanraure Hachinohe FC", ["V-Varen Nagasaki", "Kashima"])[0])
        for name, candidates, expected in cases:
            self.assertEqual(match_team(name, candidates)[0], expected, name)


class BetPawaParser(unittest.TestCase):
    def test_saved_page(self):
        with open(os.path.join(ROOT, "debug_text.txt"), encoding="utf-8") as f:
            events = parse_page_text(f.read())
        self.assertEqual(len(events), 20)
        first = events[0]
        self.assertEqual((first["home"], first["away"]), ("Petrojet FC", "Talaea El Gaish"))
        self.assertEqual(first["league"], "Football / Egypt / Premier League")
        self.assertEqual(first["odds"], [2.55, 2.84, 2.98])
        self.assertTrue(all(e["odds"] is None or len(e["odds"]) == 3 for e in events))

    def test_event_without_odds(self):
        text = "10:30 pm Thu 05/03\nAlpha FC\nBeta United\nFootball / Spain / LaLiga\n1\nX\n2\n"
        events = parse_page_text(text)
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["odds"])

    def test_navigation_text_is_not_a_team(self):
        text = "10:30 pm Thu 05/03\nLOGIN\nJOIN NOW\n"
        self.assertEqual(parse_page_text(text), [])


if __name__ == "__main__":
    unittest.main()
