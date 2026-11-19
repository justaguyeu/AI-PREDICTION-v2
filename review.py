"""
Weekly review: what would the system have predicted, and what actually happened?
=================================================================================
1. Grades the predictions you saved with predict_today.py (results from
   football-data.co.uk, or ESPN for leagues/days it does not cover).
2. Simulates the system on every match played in the window: the model is
   refitted on results known BEFORE the match, the match is predicted exactly
   like predict_today.py does, and every market is graded.
   - matches with published odds  -> full system (model + odds)
   - matches only on ESPN so far  -> model only (odds not published yet)

  python review.py                                   # last 7 days
  python review.py --start 2026-10-13 --end 2026-10-19 --show 100
  python review.py --start 2025-08-01 --refit weekly --calibrate   # rebuild engine/calibration.json
"""
import argparse
import datetime
import glob
import json
import os
import re
import sys
import warnings
from collections import defaultdict

import numpy as np
import pandas as pd

from engine import calibration
from engine import dixon_coles as dc
from engine.data import LEAGUES, _similarity, country_codes, load_country, match_team, normalise_name
from engine.market import implied_probs
from engine.model import MODEL_VERSION, draw_risk, predict_with_model
from engine.results import espn_results
from engine.storage import STORAGE_DIR

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RES = {0: "HOME WIN", 1: "DRAW", 2: "AWAY WIN"}


def _f(conf) -> float:
    return float(str(conf).rstrip("%")) / 100


def _ou_hit(pick: str, goals: float) -> bool:
    side, line = pick.split()
    return goals > float(line) if side == "OVER" else goals < float(line)


def grade(pred: dict, hg: int, ag: int, hthg=None, htag=None) -> list[dict]:
    """One row per market: market, pick, prob, hit."""
    m = pred["markets"]
    res = 0 if hg > ag else (1 if hg == ag else 2)
    out = []

    def add(market, pick, prob, hit):
        out.append({"market": market, "pick": pick, "prob": prob, "hit": bool(hit)})

    add("1X2", m["1x2_ft"]["prediction"], _f(m["1x2_ft"]["confidence"]), m["1x2_ft"]["prediction"] == RES[res])
    dcp = m["double_chance"]["prediction"].split()[0]
    add("Double chance", dcp, _f(m["double_chance"]["confidence"]),
        {"1X": res != 2, "X2": res != 0, "12": res != 1}[dcp])
    for t in m["ou_ft"]["all_thresholds"]:
        line = float(t["label"][1:])
        if line in (1.5, 2.5, 3.5):
            pick = f"{t['pick']} {line}"
            add(f"O/U {line}", pick, t["confidence"] / 100, _ou_hit(pick, hg + ag))
    add("BTTS", m["btts"]["prediction"], _f(m["btts"]["confidence"]),
        (hg > 0 and ag > 0) == (m["btts"]["prediction"] == "YES"))
    add("Home O/U 1.5", m["ou_home"]["prediction"], _f(m["ou_home"]["confidence"]), _ou_hit(m["ou_home"]["prediction"], hg))
    add("Away O/U 1.5", m["ou_away"]["prediction"], _f(m["ou_away"]["confidence"]), _ou_hit(m["ou_away"]["prediction"], ag))
    hcp = m["handicap"]["prediction"]
    add("Handicap -1", hcp, _f(m["handicap"]["confidence"]),
        {"1 (-1)": hg - ag >= 2, "X (-1)": hg - ag == 1, "2 (-1)": hg - ag <= 0}[hcp])
    top = pred["correct_scores"][0]
    add("Correct score", top["score"], top["prob"] / 100, top["score"] == f"{hg} - {ag}")

    if hthg is not None and np.isfinite(hthg) and np.isfinite(htag):
        hthg, htag = int(hthg), int(htag)
        ht = 0 if hthg > htag else (1 if hthg == htag else 2)
        add("1X2 1st half", m["1x2_h1"]["prediction"], _f(m["1x2_h1"]["confidence"]), m["1x2_h1"]["prediction"] == RES[ht])
        add("O/U 1st half", m["ou_h1"]["prediction"], _f(m["ou_h1"]["confidence"]), _ou_hit(m["ou_h1"]["prediction"], hthg + htag))
        sh, sa = hg - hthg, ag - htag
        sres = 0 if sh > sa else (1 if sh == sa else 2)
        add("1X2 2nd half", m["1x2_h2"]["prediction"], _f(m["1x2_h2"]["confidence"]), m["1x2_h2"]["prediction"] == RES[sres])
        add("O/U 2nd half", m["ou_h2"]["prediction"], _f(m["ou_h2"]["confidence"]), _ou_hit(m["ou_h2"]["prediction"], sh + sa))
        htft = f"{'1X2'[ht]}/{'1X2'[res]}"
        add("HT/FT", m["ht_ft"]["prediction"], _f(m["ht_ft"]["confidence"]), m["ht_ft"]["prediction"] == htft)
    return out


# ── Simulation ───────────────────────────────────────────────────────────────

def _espn_for_country(espn: pd.DataFrame, codes: list[str], teams: list[str], fd_window: pd.DataFrame):
    """ESPN matches of these leagues that football-data has not published yet, with fd team names."""
    rows = []
    published = {(r.home, r.away): r.date for r in fd_window.itertuples()}
    for r in espn[espn["league"].isin(codes)].itertuples():
        h, _ = match_team(r.home, teams)
        a, _ = match_team(r.away, teams)
        if not h or not a or h == a:
            continue
        if (h, a) in published and abs((published[(h, a)] - r.date).days) <= 1:
            continue
        rows.append({"date": r.date, "league": r.league, "home": h, "away": a, "hg": r.hg, "ag": r.ag,
                     "hthg": None, "htag": None, "odds": None, "source": "espn"})
    return rows


def simulate(start, end, leagues, refit="daily", use_espn=True):
    out = []
    groups = defaultdict(list)
    for code in leagues:
        groups[country_codes(code)[0]].append(code)
    espn = espn_results(start.date(), end.date()) if use_espn else pd.DataFrame(columns=["league"])

    for key, codes in groups.items():
        df = load_country(key, today=max(end.date(), datetime.date.today()), seasons=3)
        if df.empty:
            continue
        played = df.dropna(subset=["hg", "ag"])
        window = played[(played["date"] >= start) & (played["date"] <= end) & played["league"].isin(codes)]
        matches = [{"date": r.date, "league": r.league, "home": r.home, "away": r.away, "hg": int(r.hg),
                    "ag": int(r.ag), "hthg": r.hthg, "htag": r.htag, "source": "fd",
                    "odds": [r.oh, r.od, r.oa] if np.isfinite([r.oh, r.od, r.oa]).all() else None}
                   for r in window.itertuples()]
        if use_espn:
            teams = sorted(set(played["home"]) | set(played["away"]))
            matches += _espn_for_country(espn, codes, teams, window)
        if not matches:
            continue

        def period(d):
            d = pd.Timestamp(d).normalize()
            return d if refit == "daily" else d - pd.Timedelta(days=d.weekday())

        by_period = defaultdict(list)
        for m in matches:
            by_period[period(m["date"])].append(m)
        for ref, ms in sorted(by_period.items()):
            model = dc.fit(played, ref_date=ref, league=key)      # only results before `ref`
            for m in ms:
                ok = model is not None and m["home"] in model.attack and m["away"] in model.attack
                pred = predict_with_model(model if ok else None, m["home"] if ok else None,
                                          m["away"] if ok else None, m["home"], m["away"], m["league"], m["odds"])
                out.append({**m, "pred": pred, "grades": grade(pred, m["hg"], m["ag"], m["hthg"], m["htag"])})
        n_fd = sum(1 for m in matches if m["source"] == "fd")
        print(f"  {key:<4} {', '.join(codes):<28} {n_fd:>5} with odds  {len(matches) - n_fd:>4} results-only",
              flush=True)
    return out


# ── Saved predictions ────────────────────────────────────────────────────────

def _date_window(pred, fdate):
    """Days a saved prediction's result may fall on: its BetPawa kickoff ('10:30 pm Thu 05/03') if stored."""
    m = re.search(r"(\d{2})/(\d{2})", pred.get("kickoff") or "")
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = fdate.year + (1 if month < fdate.month - 6 else 0)
        try:
            k = pd.Timestamp(year=year, month=month, day=day)
            return k - pd.Timedelta(days=1), k + pd.Timedelta(days=1)
        except ValueError:
            pass
    return fdate - pd.Timedelta(days=1), fdate + pd.Timedelta(days=7)


def _find_espn(pred, fdate, espn, espn_norm):
    lo, hi = _date_window(pred, fdate)
    h, a = normalise_name(pred["home"]), normalise_name(pred["away"])
    best, best_score = None, 0.0
    for i in np.where((espn["date"] >= lo) & (espn["date"] <= hi))[0]:
        sh = _similarity(h, espn_norm[i][0])
        if sh < 0.8:
            continue
        sa = _similarity(a, espn_norm[i][1])
        if sa >= 0.8 and sh + sa > best_score:
            best, best_score = espn.iloc[i], sh + sa
    return best


MANUAL_RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "manual_results.csv")
MANUAL_COLUMNS = ["date", "league", "home", "away", "home_goals", "away_goals"]


def load_manual_results() -> pd.DataFrame:
    """Scores you typed in yourself (data/manual_results.csv) for leagues no free source covers."""
    empty = pd.DataFrame(columns=MANUAL_COLUMNS + ["hg", "ag", "nh", "na"])
    if not os.path.exists(MANUAL_RESULTS):
        return empty
    df = pd.read_csv(MANUAL_RESULTS, dtype=str).fillna("")
    if df.empty:
        return empty
    df = df[(df["home_goals"].str.strip() != "") & (df["away_goals"].str.strip() != "")]
    df = df.assign(date=pd.to_datetime(df["date"], errors="coerce"),
                   hg=pd.to_numeric(df["home_goals"], errors="coerce"),
                   ag=pd.to_numeric(df["away_goals"], errors="coerce")).dropna(subset=["date", "hg", "ag"])
    df["nh"] = df["home"].map(normalise_name)
    df["na"] = df["away"].map(normalise_name)
    return df


class ResultFinder:
    """Final score for a saved prediction: your manual results, then football-data, then ESPN."""

    def __init__(self, start, end):
        self.espn = espn_results((start - pd.Timedelta(days=8)).date(),
                                 min(end + pd.Timedelta(days=1), pd.Timestamp(datetime.date.today())).date())
        self.espn_norm = [(normalise_name(r.home), normalise_name(r.away)) for r in self.espn.itertuples()]
        self.manual = load_manual_results()
        self.fd_cache = {}

    def find(self, pred, fdate):
        lo, hi = _date_window(pred, fdate)
        h, a = normalise_name(pred["home"]), normalise_name(pred["away"])
        m = self.manual[(self.manual["nh"] == h) & (self.manual["na"] == a) &
                        (self.manual["date"] >= lo) & (self.manual["date"] <= hi)]
        if not m.empty:
            r = m.iloc[0]
            return {"date": r["date"], "hg": int(r["hg"]), "ag": int(r["ag"]), "hthg": None, "htag": None}, "manual"
        teams = (pred.get("analysis_meta") or {}).get("matched_teams")
        if teams:
            for code in LEAGUES:
                ck = country_codes(code)[0]
                if ck not in self.fd_cache:
                    self.fd_cache[ck] = load_country(ck)
                df = self.fd_cache[ck]
                hit = df[(df["home"] == teams[0]) & (df["away"] == teams[1]) & (df["date"] >= lo)
                         & (df["date"] <= hi)].dropna(subset=["hg"])
                if not hit.empty:
                    r = hit.iloc[0]
                    return {"date": r["date"], "hg": int(r["hg"]), "ag": int(r["ag"]),
                            "hthg": r["hthg"], "htag": r["htag"]}, "football-data"
        r = _find_espn(pred, fdate, self.espn, self.espn_norm)
        if r is not None:
            return {"date": r["date"], "hg": int(r["hg"]), "ag": int(r["ag"]), "hthg": None, "htag": None}, "ESPN"
        return None, None


def _saved_files(lo, hi):
    return [p for p in sorted(glob.glob(os.path.join(STORAGE_DIR, "predictions_*.json")))
            if lo <= pd.Timestamp(os.path.basename(p)[12:22]) <= hi]


def saved_predictions(start, end):
    files = _saved_files(start - pd.Timedelta(days=7), end)
    if not files:
        return [], 0
    finder = ResultFinder(start, end)
    rows, missing, seen = [], 0, set()
    for path in files:
        fdate = pd.Timestamp(os.path.basename(path)[12:22])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for pred in data.values():
            key = (pred["home"], pred["away"])
            if key in seen or pred.get("engine") is None:
                continue
            seen.add(key)
            result, src = finder.find(pred, fdate)
            if result is None:
                missing += 1
                continue
            rows.append({"league": pred.get("league") or "", "date": result["date"], "home": pred["home"],
                         "away": pred["away"], "hg": result["hg"], "ag": result["ag"], "pred": pred,
                         "odds": pred.get("odds"), "source": src,
                         "grades": grade(pred, result["hg"], result["ag"], result["hthg"], result["htag"])})
    return rows, missing


# ── Reporting ────────────────────────────────────────────────────────────────

def report(rows, show=0, title=""):
    if title:
        print(f"\n--- {title} ---")
    if not rows:
        print("  No graded matches.")
        return
    g = pd.DataFrame([dict(x, league=r["league"]) for r in rows for x in r["grades"]])

    g["cal"] = [calibration.hit_rate(m, p) for m, p in zip(g["market"], g["prob"])]
    print(f"  {len(rows)} matches graded\n")
    print(f"  {'market':<16}{'picks':>6}{'model':>8}{'calibr.':>9}{'hit rate':>10}   "
          f"{'brier raw -> calibr.':<22}verdict (calibrated)")
    for mk, sub in g.groupby("market", sort=False):
        exp, cal, act = sub["prob"].mean(), sub["cal"].mean(), sub["hit"].mean()
        b_raw = ((sub["prob"] - sub["hit"]) ** 2).mean()
        b_cal = ((sub["cal"] - sub["hit"]) ** 2).mean()
        verdict = "as expected" if abs(act - cal) <= 2 * np.sqrt(cal * (1 - cal) / len(sub)) else \
                  ("BETTER than expected" if act > cal else "WORSE than expected")
        print(f"  {mk:<16}{len(sub):>6}{exp:>8.1%}{cal:>9.1%}{act:>10.1%}   "
              f"{b_raw:.4f} -> {b_cal:.4f}      {verdict}")

    x = g[g["market"] == "1X2"]
    print(f"\n  1X2 by confidence")
    print(f"  {'model prob':<12}{'picks':>6}{'model':>8}{'calibr.':>9}{'hit rate':>10}")
    for lo, hi in [(0, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)]:
        s = x[(x["prob"] >= lo) & (x["prob"] < hi)]
        if len(s):
            print(f"  {lo:.0%}-{min(hi, 1):.0%}{'':<5}{len(s):>6}{s['prob'].mean():>8.1%}"
                  f"{s['cal'].mean():>9.1%}{s['hit'].mean():>10.1%}")

    safest = [r["pred"].get("safest_pick") for r in rows]
    if any(safest):
        hits = []
        for r, sp in zip(rows, safest):
            if not sp:
                continue
            gr = {x["market"]: x for x in r["grades"]}
            if sp["market"] in gr and gr[sp["market"]]["pick"].split()[0] in sp["pick"]:
                hits.append((sp["hit_rate"], gr[sp["market"]]["hit"]))
        if hits:
            hr = np.array(hits, dtype=float)
            print(f"\n  Safest pick per match: {len(hr)} picks, expected {hr[:, 0].mean() / 100:.1%}, "
                  f"won {hr[:, 1].mean():.1%}")
            print(f"  {'stated hit rate':<16}{'picks':>6}{'expected':>10}{'won':>8}{'fair odds':>11}")
            for lo, hi in [(0, 70), (70, 80), (80, 85), (85, 90), (90, 101)]:
                s = hr[(hr[:, 0] >= lo) & (hr[:, 0] < hi)]
                if len(s):
                    print(f"  {lo:>3}-{min(hi, 100)}%{'':<9}{len(s):>6}{s[:, 0].mean() / 100:>10.1%}"
                          f"{s[:, 1].mean():>8.1%}{100 / s[:, 0].mean():>11.2f}")

    res = np.array([0 if r["hg"] > r["ag"] else (1 if r["hg"] == r["ag"] else 2) for r in rows])
    print(f"\n  Results: home wins {np.mean(res == 0):.1%} | draws {np.mean(res == 1):.1%} "
          f"| away wins {np.mean(res == 2):.1%}")

    levels = np.array([draw_risk(r["pred"]["markets"]["1x2_ft"]["options"]["X"] / 100)["level"] for r in rows])
    print("  Draw risk:   " + "   ".join(
        f"{lvl} {np.sum(levels == lvl)} matches -> {np.mean(res[levels == lvl] == 1):.0%} draws"
        for lvl in ("LOW", "MEDIUM", "HIGH") if np.any(levels == lvl)))

    metrics = validation_tables(rows, res)

    if show:
        print(f"\n  {'date':<11}{'match':<46}{'score':>6}  {'1X2 pick':<10}{'prob':>6}  {'O/U 2.5':<11}{'BTTS':<5}")
        for r in sorted(rows, key=lambda r: r["date"])[:show]:
            gr = {x["market"]: x for x in r["grades"]}
            mark = lambda k: "✓" if gr[k]["hit"] else "✗"
            print(f"  {pd.Timestamp(r['date']):%Y-%m-%d} {(r['home'] + ' v ' + r['away'])[:45]:<46}"
                  f"{r['hg']:>3}-{r['ag']:<2} {mark('1X2')} {gr['1X2']['pick']:<9}{gr['1X2']['prob']:>6.0%}  "
                  f"{mark('O/U 2.5')} {gr['O/U 2.5']['pick']:<9} {mark('BTTS')} {gr['BTTS']['pick']}")
    return metrics


def _scores(P, y):
    P = np.clip(np.asarray(P, dtype=float), 1e-12, 1)
    acc = float(np.mean(P.argmax(1) == y))
    ll = float(-np.mean(np.log(P[np.arange(len(y)), y])))
    brier = float(np.mean(((P - np.eye(3)[y]) ** 2).sum(1)))
    return acc, ll, brier


def validation_tables(rows, res) -> dict:
    """Baselines, confusion matrix, per-league table and value-flag results for the 1X2 market."""
    P = np.array([[r["pred"]["markets"]["1x2_ft"]["options"][k] for k in "1X2"] for r in rows], dtype=float) / 100
    P = P / P.sum(1, keepdims=True)
    mk = [implied_probs(r.get("odds")) for r in rows]
    has_mk = np.array([m is not None for m in mk])

    print(f"\n  1X2 compared with simple baselines (lower log-loss / Brier = better probabilities)")
    print(f"  {'predictor':<27}{'matches':>8}{'accuracy':>10}{'log-loss':>10}{'Brier':>8}")
    acc, ll, br = _scores(P, res)
    print(f"  {'this system':<27}{len(res):>8}{acc:>10.1%}{ll:>10.4f}{br:>8.4f}")
    l3 = None
    if has_mk.sum():
        a2, l2, b2 = _scores(P[has_mk], res[has_mk])
        a3, l3, b3 = _scores(np.vstack([m for m in mk if m is not None]), res[has_mk])
        print(f"  {'this system (rows w/ odds)':<27}{has_mk.sum():>8}{a2:>10.1%}{l2:>10.4f}{b2:>8.4f}")
        print(f"  {'bookmaker odds only':<27}{has_mk.sum():>8}{a3:>10.1%}{l3:>10.4f}{b3:>8.4f}")
    home = np.tile([0.46, 0.26, 0.28], (len(res), 1))
    a4, l4, b4 = _scores(home, res)
    print(f"  {'always home win (46/26/28)':<27}{len(res):>8}{a4:>10.1%}{l4:>10.4f}{b4:>8.4f}")
    a5, l5, b5 = _scores(np.full((len(res), 3), 1 / 3), res)
    print(f"  {'uniform 33/33/33':<27}{len(res):>8}{a5:>10.1%}{l5:>10.4f}{b5:>8.4f}")

    pick = P.argmax(1)
    print(f"\n  Confusion matrix (rows = predicted, columns = actual)")
    print(f"  {'':<12}{'home win':>10}{'draw':>8}{'away win':>10}{'total':>8}{'correct':>9}")
    for i, name in enumerate(("home win", "draw", "away win")):
        row = [int(np.sum((pick == i) & (res == j))) for j in range(3)]
        tot = sum(row)
        print(f"  {name:<12}{row[0]:>10}{row[1]:>8}{row[2]:>10}{tot:>8}"
              f"{(row[i] / tot if tot else float('nan')):>9.1%}")

    leagues = np.array([str(r["league"]).replace("Football / ", "") for r in rows])
    if len(set(leagues)) > 1:
        print(f"\n  {'by league':<31}{'matches':>8}{'accuracy':>10}{'log-loss':>10}{'bookmaker':>11}")
        for lg in sorted(set(leagues)):
            m = leagues == lg
            a, l, _ = _scores(P[m], res[m])
            mm = m & has_mk
            lb = _scores(np.vstack([mk[i] for i in np.where(mm)[0]]), res[mm])[1] if mm.sum() else float("nan")
            print(f"  {lg[:30]:<31}{m.sum():>8}{a:>10.1%}{l:>10.4f}{lb:>11.4f}")

    # Value flags as the live system would raise them, settled at the supplied odds
    stake = ret = curve = peak = dd = 0.0
    thr = None
    for r, y in sorted(zip(rows, res), key=lambda t: t[0]["date"]):
        v = r["pred"].get("value")
        if not v:
            continue
        thr = v["threshold"]
        for i, o in enumerate(v["outcomes"]):
            if o["flag"]:
                stake += 1
                win = o["odds"] if y == i else 0.0
                ret += win
                curve += win - 1
                peak = max(peak, curve)
                dd = max(dd, peak - curve)
    if stake:
        print(f"\n  Value flags (model EV >= {thr}%): {int(stake)} bets, ROI {ret / stake - 1:+.1%}, max drawdown "
              f"{dd:.0f} units (settled at the odds used for the prediction)")
    else:
        print("\n  Value flags: none raised in this period" +
              (" (flags are off: set VALUE_EV_THRESHOLD to test them)." if thr is None else "."))
    return {"matches": int(len(res)), "accuracy": acc, "log_loss": ll, "brier": br,
            "bookmaker_log_loss": l3, "value_bets": int(stake), "value_roi": (ret / stake - 1 if stake else None)}


# ── Post-mortem of one day ───────────────────────────────────────────────────

def _kickoff_day(pred, fdate):
    lo, hi = _date_window(pred, fdate)
    return lo + pd.Timedelta(days=1) if pred.get("kickoff") else None


def postmortem(day: pd.Timestamp, add_missing: bool = False) -> None:
    """Match-by-match look at the saved predictions whose kickoff was on `day`."""
    preds = {}
    for path in _saved_files(day - pd.Timedelta(days=3), day):
        fdate = pd.Timestamp(os.path.basename(path)[12:22])
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for key, pred in data.items():
            kd = _kickoff_day(pred, fdate)
            if (kd if kd is not None else fdate) != day or pred.get("status") != "success":
                continue
            match = (pred["home"], pred["away"])
            newer = "@" not in key                         # "...@dc-v3" = an older engine's copy
            if match not in preds or (newer and preds[match][2] is False):
                preds[match] = (pred, fdate, newer)
    print(f"=== Post-mortem: predictions with kickoff on {day:%a %d %b %Y} ({len(preds)} matches) ===")
    if not preds:
        print("  No saved predictions for that day.")
        return

    finder = ResultFinder(day, day)
    graded, missing = [], []
    for pred, fdate, _ in preds.values():
        result, src = finder.find(pred, fdate)
        (graded if result else missing).append((pred, result, src))

    exp_wins = var = 0.0
    wins = sp_won = sp_n = 0
    closer = {"bookmaker": 0, "ratings model": 0}
    outcomes = {"correct": 0, "draw": 0, "upset": 0}
    for pred, r, src in sorted(graded, key=lambda t: str(t[0].get("kickoff"))):
        hg, ag = r["hg"], r["ag"]
        res = 0 if hg > ag else (1 if hg == ag else 2)
        o = pred["markets"]["1x2_ft"]["options"]
        P = np.array([o["1"], o["X"], o["2"]], dtype=float)
        P = P / P.sum()
        pick = int(P.argmax())
        exp_wins += P[pick]
        var += P[pick] * (1 - P[pick])
        wins += pick == res
        if pick == res:
            verdict = "correct"
        elif res == 1:
            verdict = "draw"
        else:
            verdict = "upset"
        outcomes[verdict] += 1
        meta = pred.get("analysis_meta") or {}
        g = {x["market"]: x for x in grade(pred, hg, ag)}
        print(f"\n  {pred.get('kickoff') or ''}  {(pred.get('league') or '').replace('Football / ', '')}"
              f"   [{meta.get('data_source')}, {pred.get('engine')}]")
        print(f"  {pred['home']} {hg}-{ag} {pred['away']}   (score from {src})")
        mark = "✓" if pick == res else "✗"
        print(f"    {mark} pick {RES[pick]} ({P[pick]:.0%}); the result had {P[res]:.0%}"
              + {"correct": "", "draw": " -> ended level", "upset": " -> upset"}[verdict])
        mo, mk = meta.get("model_1x2"), meta.get("market_1x2")
        if mo and mk:
            key = "1X2"[res]
            who = "bookmaker" if mk[key] >= mo[key] else "ratings model"
            closer[who] += 1
            print(f"    result chance: bookmaker {mk[key]}% vs ratings model {mo[key]}% -> {who} was closer")
        sp = pred.get("safest_pick")
        if sp and sp["market"] in g:
            ok = g[sp["market"]]["hit"]
            sp_n += 1
            sp_won += ok
            print(f"    safest pick {sp['market']}: {sp['pick']} ({sp['hit_rate']}%) {'✓' if ok else '✗'}")
        print(f"    O/U 2.5 {g['O/U 2.5']['pick']} {'✓' if g['O/U 2.5']['hit'] else '✗'}  "
              f"BTTS {g['BTTS']['pick']} {'✓' if g['BTTS']['hit'] else '✗'}  "
              f"draw risk {(pred.get('draw_risk') or {}).get('level', '?')}")
        for risk in pred.get("risks") or []:
            if "rejected" in risk or "fewer than" in risk or "disagree" in risk:
                print(f"    note: {risk}")

    if graded:
        sd = np.sqrt(var)
        z = (wins - exp_wins) / sd if sd else 0.0
        print(f"\n  Summary of {len(graded)} graded matches")
        print(f"    1X2 picks won {wins}; their own probabilities expected {exp_wins:.1f} "
              f"(normal range {max(exp_wins - 2 * sd, 0):.1f} to {exp_wins + 2 * sd:.1f})")
        print(f"    misses: {outcomes['draw']} draws, {outcomes['upset']} upsets")
        if sp_n:
            print(f"    safest picks won {sp_won} of {sp_n}")
        if sum(closer.values()):
            print(f"    on the actual result the bookmaker was closer {closer['bookmaker']} times, the ratings "
                  f"model {closer['ratings model']} times")
        if abs(z) <= 2:
            print("    verdict: within the normal range of luck for this many matches - no sign the system "
                  "itself went wrong")
        else:
            print(f"    verdict: {'better' if z > 0 else 'worse'} than the normal range - worth investigating")

    if missing:
        print(f"\n  No result available for {len(missing)} matches (league not covered by football-data or ESPN):")
        for pred, _, _ in missing:
            print(f"    {(pred.get('kickoff') or '')[:18]:<19}{(pred.get('league') or '').replace('Football / ', '')[:38]:<39}"
                  f"{pred['home']} v {pred['away']}")
        if add_missing:
            added = add_to_manual_results(day, [m[0] for m in missing])
            print(f"\n  Added {added} of them to {MANUAL_RESULTS}: type in the scores, then run this again.")
        else:
            print(f"  Run with --add-missing to list them in {os.path.basename(MANUAL_RESULTS)} so you can type "
                  f"in the scores yourself.")


def add_to_manual_results(day, preds) -> int:
    """Append matches (with empty scores) to data/manual_results.csv, skipping ones already listed."""
    import csv
    os.makedirs(os.path.dirname(MANUAL_RESULTS), exist_ok=True)
    existing = set()
    if os.path.exists(MANUAL_RESULTS):
        with open(MANUAL_RESULTS, encoding="utf-8", newline="") as f:
            existing = {(r["date"], r["home"], r["away"]) for r in csv.DictReader(f)}
    new = not os.path.exists(MANUAL_RESULTS)
    added = 0
    with open(MANUAL_RESULTS, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MANUAL_COLUMNS)
        if new:
            w.writeheader()
        for p in preds:
            row = {"date": f"{day:%Y-%m-%d}", "league": (p.get("league") or "").replace("Football / ", ""),
                   "home": p["home"], "away": p["away"], "home_goals": "", "away_goals": ""}
            if (row["date"], row["home"], row["away"]) not in existing:
                w.writerow(row)
                added += 1
    return added


MONITOR_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "monitoring", "review_log.csv")


def log_metrics(start, end, m: dict) -> None:
    """Append one line per review run, so changes in performance over time are visible."""
    os.makedirs(os.path.dirname(MONITOR_LOG), exist_ok=True)
    new = not os.path.exists(MONITOR_LOG)
    fmt = lambda v: "" if v is None else (f"{v:.4f}" if isinstance(v, float) else str(v))
    with open(MONITOR_LOG, "a", encoding="utf-8") as f:
        if new:
            f.write("run_at,model_version,start,end,matches,accuracy,log_loss,brier,bookmaker_log_loss,"
                    "value_bets,value_roi\n")
        f.write(",".join([datetime.datetime.now().isoformat(timespec="seconds"), MODEL_VERSION,
                          str(start.date()), str(end.date())] +
                         [fmt(m[k]) for k in ("matches", "accuracy", "log_loss", "brier", "bookmaker_log_loss",
                                              "value_bets", "value_roi")]) + "\n")
    print(f"\n  Logged to {MONITOR_LOG}")


def main():
    today = pd.Timestamp(datetime.date.today())
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=str((today - pd.Timedelta(days=7)).date()))
    ap.add_argument("--end", default=str((today - pd.Timedelta(days=1)).date()))
    ap.add_argument("--leagues", nargs="+", default=list(LEAGUES))
    ap.add_argument("--refit", choices=["daily", "weekly"], default="daily")
    ap.add_argument("--no-espn", action="store_true")
    ap.add_argument("--show", type=int, default=0, help="print N individual matches")
    ap.add_argument("--day", help="post-mortem of the saved predictions that kicked off on this date (YYYY-MM-DD)")
    ap.add_argument("--yesterday", action="store_true", help="post-mortem of yesterday's saved predictions")
    ap.add_argument("--add-missing", action="store_true",
                    help="with --day/--yesterday: list ungraded matches in data/manual_results.csv for you to fill in")
    ap.add_argument("--calibrate", action="store_true",
                    help="rebuild engine/calibration.json from the graded matches with odds")
    args = ap.parse_args()
    start, end = pd.Timestamp(args.start), pd.Timestamp(args.end)

    if args.day or args.yesterday:
        day = pd.Timestamp(args.day) if args.day else today - pd.Timedelta(days=1)
        postmortem(day.normalize(), add_missing=args.add_missing)
        return

    if not args.calibrate:
        print(f"=== Your saved predictions, {start:%d %b} - {end:%d %b} ===")
        saved, missing = saved_predictions(start, end)
        report(saved, args.show)
        if missing:
            print(f"  ({missing} saved predictions without a result yet: not played, or league not covered)")

    print(f"\n=== Simulated system, {start:%d %b %Y} - {end:%d %b %Y} ===")
    rows = simulate(start, end, args.leagues, args.refit, use_espn=not args.no_espn)
    with_odds = [r for r in rows if r["odds"] is not None]
    metrics = report(with_odds, args.show, "Full system: model + odds")
    report([r for r in rows if r["odds"] is None], args.show, "Model only: results published, odds not yet")
    if metrics and not args.calibrate:
        log_metrics(start, end, metrics)

    if args.calibrate:
        g = pd.DataFrame([x for r in with_odds for x in r["grades"]])
        path = calibration.save(calibration.build(g), meta={
            "matches": len(with_odds), "start": str(start.date()), "end": str(end.date())})
        print(f"\nSaved calibration for {g['market'].nunique()} markets to {path}")


if __name__ == "__main__":
    main()
