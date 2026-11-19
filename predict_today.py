"""
CLI Prediction Runner
=====================
Pulls upcoming matches (with league + odds) from BetPawa and predicts all 14 markets.

  python predict_today.py                     # scrape BetPawa live
  python predict_today.py --file page.txt     # use saved page text instead of scraping
  python predict_today.py --top 15            # size of the "top picks" summary
"""
import argparse
import datetime
import sys

from engine.betpawa import parse_page_text, scrape_matches
from engine.model import predict_match
from engine.storage import get_prediction, save_prediction

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

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
SOURCE_LABEL = {"model+market": "results model + odds", "market": "odds only",
                "model": "results model only", "none": "NO DATA"}


def print_predictions(pred: dict):
    meta = pred.get("analysis_meta", {})
    print(f"\n{'=' * 70}")
    print(f"  {pred['home'].upper()} vs {pred['away'].upper()}")
    if pred.get("league"):
        print(f"  {pred['league']}")
    a = pred.get("assessment") or {}
    if a:
        print(f"  Prediction strength: {a['prediction_strength']['level']}  |  "
              f"Model confidence: {a['model_confidence']['level']}  |  "
              f"Data quality: {a['data_quality']['level']} ({SOURCE_LABEL.get(meta.get('data_source'), '?')})")
    else:
        print(f"  Confidence: {pred.get('overall_confidence')}  |  Data: {SOURCE_LABEL.get(meta.get('data_source'), '?')}")
    print(f"  xG -> Home {meta.get('home_xg')} | Away {meta.get('away_xg')}")
    if meta.get("model_1x2") and meta.get("market_1x2"):
        mo, mk = meta["model_1x2"], meta["market_1x2"]
        print(f"  Model 1/X/2: {mo['1']}/{mo['X']}/{mo['2']}%   Bookmaker: {mk['1']}/{mk['X']}/{mk['2']}%")
    o = pred["markets"]["1x2_ft"]["options"]
    dr = pred.get("draw_risk")
    print(f"  Final: Home {o['1']}% | Draw {o['X']}% | Away {o['2']}%"
          + (f"   -> draw risk {dr['level']}" if dr else ""))
    print(f"{'=' * 70}")

    markets = pred.get("markets", {})
    print(f"  {'market':<38}  {'pick':<20}  {'model':>6}  {'hit rate':>8}")
    for key, label in MARKET_DISPLAY_ORDER:
        m = markets.get(key)
        if m:
            print(f"  [{label[:36]:<36}]  {m['prediction']:<20}  {m['confidence']:>6}  {m.get('hit_rate', ''):>8}")

    sp = pred.get("safest_pick")
    if sp:
        print(f"\n  SAFEST PICK: {sp['market']} -> {sp['pick']}  "
              f"(won {sp['hit_rate']:.0f}% of the time historically; fair odds {sp['fair_odds']})")
    scores = pred.get("correct_scores", [])
    if scores:
        print("  Likely scores: " + ", ".join(f"{s['score']} ({s['prob']:.1f}%)" for s in scores[:4]))

    v = pred.get("value")
    if v:
        flags = "value flags OFF" if v["threshold"] is None else f"value flag at model EV >= {v['threshold']}%"
        print(f"\n  Odds check (bookmaker margin {v['overround']}%; {flags}):")
        for o in v["outcomes"]:
            model = (f"  ratings model {o['model_probability']:>5.1f}% (EV {o['ev_model']:+6.1f}%)"
                     if o["model_probability"] is not None else "")
            print(f"    {o['outcome']:<9} odds {o['odds']:>6.2f}  fair {o['fair']:>5.1f}%{model}"
                  + ("   <- worth a closer look (not expected profit)" if o["flag"] else ""))

    factors, risks = pred.get("factors"), pred.get("risks")
    if factors:
        print("\n  Why:")
        for f in factors:
            print(f"    {f}")
    else:
        print(f"\n  {pred.get('reasoning', '')}")
    if risks:
        print("  What could make it wrong:")
        for r in risks:
            print(f"    - {r}")


def _hit(p, key="1x2_ft"):
    return float(p["markets"][key].get("hit_rate", p["markets"][key]["confidence"]).rstrip("%"))


def print_summary(preds: list[dict], top: int):
    usable = [p for p in preds if p["analysis_meta"]["data_source"] != "none"]
    if not usable:
        print("\n  No match had results data or odds.")
        return

    play = sorted((p for p in usable if _hit(p) >= 60), key=lambda p: -_hit(p))
    lean = [p for p in usable if 50 <= _hit(p) < 60]
    flips = [p for p in usable if _hit(p) < 50]

    print(f"\n\n{'#' * 78}")
    print(f"  MATCH RESULT (1X2) PICKS WORTH PLAYING: {len(play)} rated 60% or more")
    print(f"  (in 2 seasons of results, picks rated 60-70% won 65%, 70%+ won about 77%)")
    print(f"{'#' * 78}")
    for p in play:
        m = p["markets"]["1x2_ft"]
        print(f"  {_hit(p):>5.1f}%  {m['prediction']:<9} {p['home'][:26]:>26} v {p['away'][:26]:<26}")
    if play:
        exp = sum(_hit(p) / 100 for p in play)
        sd = sum((_hit(p) / 100) * (1 - _hit(p) / 100) for p in play) ** 0.5
        print(f"\n  Expect about {exp:.0f} of these {len(play)} to win (normal range {max(exp - 2 * sd, 0):.0f}"
              f" to {min(exp + 2 * sd, len(play)):.0f}). Some WILL lose: that is how probabilities work.")
    else:
        print("  None today.")
    print(f"\n  Not worth a match-result bet: {len(lean)} picks rated 50-60% (won ~53%) and {len(flips)} coin flips")
    print("  under 50%. For those, use the safest pick below or skip the match.")

    print(f"\n{'#' * 78}")
    print(f"  TOP {min(top, len(usable))} SAFEST PICKS (any market), ranked by historical hit rate")
    print(f"{'#' * 78}")
    for p in sorted(usable, key=lambda p: -p["safest_pick"]["hit_rate"])[:top]:
        sp = p["safest_pick"]
        print(f"  {sp['hit_rate']:>5.1f}%  fair odds {sp['fair_odds']:<5} {sp['market'] + ': ' + sp['pick']:<26} "
              f"{p['home'][:20]:>20} v {p['away'][:20]:<20}")

    draws = sorted((p for p in usable if p.get("draw_risk", {}).get("level") == "HIGH"),
                   key=lambda p: -p["draw_risk"]["prob"])
    print(f"\n{'#' * 78}")
    print(f"  DRAW WATCH: {len(draws)} matches with HIGH draw risk (draw probability 30%+)")
    print(f"{'#' * 78}")
    if draws:
        for p in draws[:top]:
            o = p["markets"]["1x2_ft"]["options"]
            dc = p["markets"]["double_chance"]["options"]
            cover = max(("1X", "X2"), key=dc.get)          # "12" loses on a draw
            print(f"  draw {o['X']:>4.1f}%  (H {o['1']:.0f}% / A {o['2']:.0f}%)  "
                  f"{p['home'][:22]:>22} v {p['away'][:22]:<22}  cover: {cover} DC {dc[cover]:.1f}%")
        print("  About 1 in 3 matches like these end level (normal: 1 in 4), so a draw is still less")
        print("  likely than not. Backing DRAW on these was tested and did not beat the 1X2 pick.")
    else:
        print("  None today.")

    skipped = [p for p in preds if p["analysis_meta"]["data_source"] == "none"]
    if skipped:
        print(f"\n  {len(skipped)} matches had no data and no odds — skip them:")
        for p in skipped:
            print(f"    - {p['home']} vs {p['away']}")
    print("\n  'Hit rate' = how often picks like this actually won in the walk-forward review")
    print("  (review.py). Safer picks pay less: a 90% pick has fair odds of 1.11, so one loss")
    print("  cancels about nine wins. No pick is certain; never stake more than you can lose.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="saved BetPawa page text to parse instead of scraping")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--quiet", action="store_true", help="only print the summary")
    ap.add_argument("--no-save", action="store_true",
                    help="do not read or write data/predictions (for test runs, e.g. with --file)")
    args = ap.parse_args()

    print("=" * 70)
    print("  BETPAWA FOOTBALL PREDICTION ENGINE (Dixon-Coles + market)")
    print(f"  {datetime.datetime.now().strftime('%A, %d %B %Y - %H:%M')}")
    print("=" * 70)

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            matches = parse_page_text(f.read())
    else:
        matches = scrape_matches()
    if not matches:
        print("\n[!] Could not load fixtures. No matches to process.")
        return
    print(f"\n[OK] Loaded {len(matches)} fixtures "
          f"({sum(1 for m in matches if m.get('odds'))} with odds)\n")

    preds = []
    for m in matches:
        home, away = m["home"], m["away"]
        pred = None if args.no_save else get_prediction(home, away)
        if not pred:
            print(f"-> {home} vs {away}")
            pred = predict_match(home, away, league=m.get("league"), odds=m.get("odds"))
            pred["kickoff"] = m.get("kickoff")
            if not args.no_save:
                save_prediction(home, away, pred)
        preds.append(pred)
        if not args.quiet:
            print_predictions(pred)

    print_summary(preds, args.top)


if __name__ == "__main__":
    main()
