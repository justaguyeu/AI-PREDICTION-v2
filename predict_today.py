"""
CLI Prediction Runner
=====================
Pulls today's matches from BetPawa and runs predictions for all 14 markets.
"""
from engine.betpawa import scrape_matches
from engine.search import build_queries
from engine.scrape import scrape_articles
from engine.nlp import analyze_text
from engine.model import predict_match
from engine.storage import save_prediction, get_prediction
import datetime
import time

MARKET_DISPLAY_ORDER = [
    ("1x2_ft",        "1X2 | Full Time"),
    ("boosted",       "Boosted Pick"),
    ("double_chance", "Double Chance | Full Time"),
    ("btts",          "Both Teams To Score | Full Time"),
    ("next_goal",     "Next Goal (Goal 1)"),
    ("ou_ft",         "Over/Under | Full Time"),
    ("ou_home",       "Over/Under | Home | Full Time"),
    ("ou_away",       "Over/Under | Away | Full Time"),
    ("ht_ft",         "Half Time / Full Time"),
    ("handicap",      "3-Way Handicap | Full Time"),
    ("1x2_h1",        "1X2 | First Half"),
    ("1x2_h2",        "1X2 | Second Half"),
    ("ou_h1",         "Over/Under | First Half"),
    ("ou_h2",         "Over/Under | Second Half"),
]

def print_predictions(pred: dict, home: str, away: str):
    print(f"\n{'=' * 65}")
    print(f"  {home.upper()} vs {away.upper()}")
    print(f"  Overall: {pred.get('overall_confidence','?')} Confidence")
    meta = pred.get("analysis_meta", {})
    print(f"  xG -> Home {meta.get('home_xg','?')} | Away {meta.get('away_xg','?')}")
    print(f"{'=' * 65}")

    markets = pred.get("markets", {})
    for key, label in MARKET_DISPLAY_ORDER:
        m = markets.get(key)
        if not m:
            continue
        pick = m.get("prediction", "?")
        conf = m.get("confidence", "?")
        print(f"  [{label[:36]:<36}]  {pick:<20}  {conf}")

    # Correct Scores
    scores = pred.get("correct_scores", [])
    if scores:
        print(f"\n  {'Likely Scores':<40}")
        for s in scores:
            print(f"    {s['score']:>8}   ->  {s['prob']:.2f}%")

def main():
    print("=" * 65)
    print("  BETPAWA FOOTBALL PREDICTION ENGINE")
    print(f"  {datetime.datetime.now().strftime('%A, %d %B %Y - %H:%M')}")
    print("=" * 65)

    matches = scrape_matches()
    if not matches:
        print("\n[!] Could not load fixtures from BetPawa. No matches to process.")
        return

    print(f"\n[OK] Loaded {len(matches)} fixtures from BetPawa TZ\n")

    for home, away in matches:
        print(f"\n-> Processing: {home} vs {away}")

        # Cache check
        cached = get_prediction(home, away)
        if cached and cached.get("status") == "success":
            print("  Loaded from cache")
            print_predictions(cached, home, away)
            continue

        # Scrape + analyse
        queries_dict = build_queries(home, away)
        texts_dict = {}
        for category, q_list in queries_dict.items():
            print(f"  > Scraping [{category}]...", end="", flush=True)
            found = scrape_articles(q_list)
            texts_dict[category] = found
            print(f" {len(found)} articles")

        analysis = analyze_text(texts_dict, home, away)

        if analysis.get("text_volume", 0) < 1:
            print("  SKIPPED - Insufficient web data")
            continue

        pred = predict_match(analysis, home_team=home, away_team=away)
        result = {"status": "success", "home": home, "away": away, **pred}
        save_prediction(home, away, result)

        print_predictions(pred, home, away)
        time.sleep(1.5)

if __name__ == "__main__":
    main()
