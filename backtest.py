"""
Walk-forward backtest
=====================
For every matchweek in the test window: fit Dixon-Coles on matches played
BEFORE that week, predict the week, compare with the real results.

Compares three predictors for 1X2:
  model   – Dixon-Coles only
  market  – bookmaker average odds (margin removed)
  blend   – log-linear pool of both (what predict_today.py uses)

Usage:
  python backtest.py                         # default leagues, since 2025-08-01
  python backtest.py --leagues E0 SP1 --since 2026-01-01
  python backtest.py --tune                  # grid-search xi / reg / market weight
"""
import argparse
import datetime
import itertools
import sys
import warnings

import numpy as np
import pandas as pd

from engine import dixon_coles as dc
from engine.data import load_country
from engine.market import MARKET_WEIGHT, blend, implied_probs, outcome_probs, rates_from_1x2

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DEFAULT_LEAGUES = ["E0", "E1", "SP1", "D1", "I1", "F1", "N1", "P1"]
WEIGHTS = [0.0, 0.25, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0]


def collect(leagues, since, xi, reg):
    """Return one row per test match with model + market probabilities."""
    rows = []
    today = datetime.date.today()
    for code in leagues:
        df = load_country(code, today, seasons=3)
        if df.empty:
            print(f"  {code}: no data"); continue
        played = df.dropna(subset=["hg", "ag"])
        test = played[(played["date"] >= pd.Timestamp(since)) & (played["league"] == code)]
        weeks = test["date"].dt.to_period("W-MON").unique()
        for wk in weeks:
            start = wk.start_time
            model = dc.fit(played, ref_date=start, xi=xi, reg=reg, league=code)
            if model is None:
                continue
            for r in test[test["date"].dt.to_period("W-MON") == wk].itertuples():
                if r.home not in model.attack or r.away not in model.attack:
                    continue
                lam, mu = model.rates(r.home, r.away)
                m = dc.score_matrix(lam, mu, model.rho)
                pm = outcome_probs(m)
                pk = implied_probs([r.oh, r.od, r.oa])
                over_mkt = None
                if np.isfinite(r.o_over25) and np.isfinite(r.o_under25) and r.o_over25 > 1 and r.o_under25 > 1:
                    inv = np.array([1 / r.o_over25, 1 / r.o_under25])
                    over_mkt = inv[0] / inv.sum()
                total = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
                over_final = None
                if pk is not None:   # what predict_match does: blend 1X2, then solve for goal rates
                    lf, mf = rates_from_1x2(blend(pm, pk, MARKET_WEIGHT), model.rho, start=(lam, mu))
                    over_final = float(dc.score_matrix(lf, mf, model.rho)[total > 2.5].sum())
                rows.append({
                    "league": code, "date": r.date,
                    "res": 0 if r.hg > r.ag else (1 if r.hg == r.ag else 2),
                    "over25": int(r.hg + r.ag > 2),
                    "pm": pm, "pk": pk, "odds": (r.oh, r.od, r.oa),
                    "over_model": float(m[total > 2.5].sum()), "over_mkt": over_mkt, "over_final": over_final,
                })
        print(f"  {code}: {sum(1 for x in rows if x['league'] == code)} test matches")
    return rows


def score(probs, res):
    p = np.vstack(probs)
    y = np.asarray(res)
    acc = (p.argmax(1) == y).mean()
    ll = -np.log(np.clip(p[np.arange(len(y)), y], 1e-12, 1)).mean()
    onehot = np.eye(3)[y]
    brier = ((p - onehot) ** 2).sum(1).mean()
    return acc, ll, brier


def report(rows):
    rows = [r for r in rows if r["pk"] is not None]
    if not rows:
        print("No test matches (download failed?)"); return None
    res = [r["res"] for r in rows]
    print(f"\n1X2 over {len(rows)} matches with odds (lower log-loss / Brier = better)")
    print(f"  {'predictor':<16}{'accuracy':>10}{'log-loss':>10}{'brier':>9}")
    for name, probs in [("model only", [r["pm"] for r in rows]),
                        ("market only", [r["pk"] for r in rows])]:
        a, l, b = score(probs, res)
        print(f"  {name:<16}{a:>9.1%}{l:>10.4f}{b:>9.4f}")
    best = None
    for w in WEIGHTS[1:-1]:
        a, l, b = score([blend(r["pm"], r["pk"], w) for r in rows], res)
        print(f"  blend w={w:<7}{a:>9.1%}{l:>10.4f}{b:>9.4f}")
        if best is None or l < best[1]:
            best = (w, l)
    print(f"  -> best market weight: {best[0]}")

    w = best[0]
    print(f"\nCalibration of the blend's top pick (w={w}): does '60%' really win 60% of the time?")
    print(f"  {'pick prob':<12}{'matches':>8}{'predicted':>11}{'actual':>9}")
    bl = [blend(r["pm"], r["pk"], w) for r in rows]
    top = np.array([p.max() for p in bl])
    hit = np.array([p.argmax() == r["res"] for p, r in zip(bl, rows)])
    for lo, hi in [(0, .4), (.4, .5), (.5, .6), (.6, .7), (.7, .8), (.8, 1.01)]:
        sel = (top >= lo) & (top < hi)
        if sel.sum():
            print(f"  {lo:.0%}-{min(hi, 1):.0%}{'':<4}{sel.sum():>8}{top[sel].mean():>10.1%}{hit[sel].mean():>9.1%}")

    ou = [r for r in rows if r["over_mkt"] is not None]
    if ou:
        y = np.array([r["over25"] for r in ou])
        for name, key in [("model", "over_model"), ("market", "over_mkt"), ("final", "over_final")]:
            p = np.array([r[key] for r in ou])
            print(f"\nOver/Under 2.5 – {name:<7} accuracy {((p > .5) == y).mean():.1%}  "
                  f"brier {((p - y) ** 2).mean():.4f}  (n={len(ou)})", end="")
        print()

    # Value betting: back the outcome when the MODEL sees ≥5% edge over average odds
    stake = ret = 0
    for r in rows:
        for i in range(3):
            o = r["odds"][i]
            if np.isfinite(o) and r["pm"][i] * o - 1 >= 0.05:
                stake += 1
                ret += o if r["res"] == i else 0
    if stake:
        print(f"\nValue bets (model edge ≥5% vs average odds): {stake} bets, ROI {ret / stake - 1:+.1%}")
    return best[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--leagues", nargs="+", default=DEFAULT_LEAGUES)
    ap.add_argument("--since", default="2025-08-01")
    ap.add_argument("--tune", action="store_true", help="grid-search xi and reg")
    args = ap.parse_args()

    if not args.tune:
        report(collect(args.leagues, args.since, dc.XI, dc.REG))
        return

    print(f"{'xi':>8}{'reg':>6}{'model log-loss':>16}{'model acc':>11}")
    for xi, reg in itertools.product([0.001, 0.0019, 0.003, 0.005], [0.5, 2.0, 5.0, 10.0]):
        rows = collect(args.leagues, args.since, xi, reg)
        a, l, _ = score([r["pm"] for r in rows], [r["res"] for r in rows])
        print(f"{xi:>8}{reg:>6}{l:>16.4f}{a:>10.1%}", flush=True)


if __name__ == "__main__":
    main()
