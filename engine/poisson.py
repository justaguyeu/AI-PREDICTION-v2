"""
engine/poisson.py
=================
Turns expected goals (λ home, μ away) and the Dixon-Coles ρ into the 14
BetPawa markets. Every market is read off the same score matrix, so the
probabilities are mutually consistent.
"""
import numpy as np

from engine.dixon_coles import score_matrix
from engine.market import outcome_probs

FIRST_HALF_SHARE = 0.45   # ~45% of goals are scored before half-time


def _ou(m: np.ndarray, line: float) -> tuple[float, float]:
    total = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
    over = float(m[total > line].sum())
    return over, 1.0 - over


def _team_ou(goal_probs: np.ndarray, line: float) -> tuple[float, float]:
    over = float(goal_probs[np.arange(len(goal_probs)) > line].sum())
    return over, 1.0 - over


def _pick_1x2(p) -> tuple[str, float]:
    i = int(np.argmax(p))
    return ["HOME WIN", "DRAW", "AWAY WIN"][i], float(p[i])


def _fmt_ou(over, under, line):
    return ("OVER " if over > under else "UNDER ") + str(line), max(over, under) * 100


def _thresholds(fn, lines):
    out = []
    for line in lines:
        ov, un = fn(line)
        out.append({"pick": "OVER" if ov > un else "UNDER",
                    "label": f"{'O' if ov > un else 'U'}{line}",
                    "confidence": round(max(ov, un) * 100, 1),
                    "over": round(ov * 100, 1)})
    return out


def correct_scores(m: np.ndarray, n: int = 6) -> list[dict]:
    flat = [(m[h, a], h, a) for h in range(m.shape[0]) for a in range(m.shape[1])]
    flat.sort(reverse=True)
    return [{"score": f"{h} - {a}", "prob": round(p * 100, 2)} for p, h, a in flat[:n]]


def all_markets(lam: float, mu: float, rho: float = 0.0, home_team: str = "", away_team: str = ""):
    """Returns (markets, correct_scores, meta)."""
    M = score_matrix(lam, mu, rho)
    M1 = score_matrix(lam * FIRST_HALF_SHARE, mu * FIRST_HALF_SHARE, 0.0, 7)
    M2 = score_matrix(lam * (1 - FIRST_HALF_SHARE), mu * (1 - FIRST_HALF_SHARE), 0.0, 7)
    markets = {}

    # 1. 1X2
    hw, dr, aw = outcome_probs(M)
    pick, p = _pick_1x2((hw, dr, aw))
    markets["1x2_ft"] = {"prediction": pick, "confidence": f"{p * 100:.1f}%",
                         "options": {"1": round(hw * 100, 1), "X": round(dr * 100, 1), "2": round(aw * 100, 1)}}

    # 2. Boosted pick: the 1X2 pick if it is a clear favourite, otherwise Over 1.5
    o15, _ = _ou(M, 1.5)
    if pick != "DRAW" and p > 0.52:
        markets["boosted"] = {"prediction": pick, "confidence": f"{p * 100:.1f}%"}
    else:
        markets["boosted"] = {"prediction": "OVER 1.5", "confidence": f"{o15 * 100:.1f}%"}

    # 3. Double chance
    dc = {"1X": round((hw + dr) * 100, 1), "X2": round((aw + dr) * 100, 1), "12": round((hw + aw) * 100, 1)}
    best_dc = max(dc, key=dc.get)
    markets["double_chance"] = {"prediction": best_dc + " DC", "confidence": f"{dc[best_dc]:.1f}%", "options": dc}

    # 4. BTTS
    btts_y = float(M[1:, 1:].sum())
    markets["btts"] = {"prediction": "YES" if btts_y > 0.5 else "NO",
                       "confidence": f"{max(btts_y, 1 - btts_y) * 100:.1f}%",
                       "options": {"YES": round(btts_y * 100, 1), "NO": round((1 - btts_y) * 100, 1)}}

    # 5. Next (first) goal
    p00 = float(M[0, 0])
    ng = {"Home": round((1 - p00) * lam / (lam + mu) * 100, 1),
          "Away": round((1 - p00) * mu / (lam + mu) * 100, 1),
          "None": round(p00 * 100, 1)}
    markets["next_goal"] = {"prediction": max(ng, key=ng.get), "confidence": f"{max(ng.values()):.1f}%", "options": ng}

    # 6. Over/Under FT
    pk, cf = _fmt_ou(*_ou(M, 2.5), 2.5)
    markets["ou_ft"] = {"prediction": pk, "confidence": f"{cf:.1f}%",
                        "all_thresholds": _thresholds(lambda l: _ou(M, l), [0.5, 1.5, 2.5, 3.5, 4.5])}

    # 7 & 8. Team totals
    for side, team, goals in [("home", home_team, M.sum(1)), ("away", away_team, M.sum(0))]:
        pk, cf = _fmt_ou(*_team_ou(goals, 1.5), 1.5)
        markets[f"ou_{side}"] = {"prediction": pk, "confidence": f"{cf:.1f}%",
                                 "all_thresholds": _thresholds(lambda l, g=goals: _team_ou(g, l), [0.5, 1.5, 2.5]),
                                 "label": f"{team} O/U | FT"}

    # 9. HT/FT
    n = M1.shape[0]
    htft = {f"{a}/{b}": 0.0 for a in "1X2" for b in "1X2"}
    sym = lambda h, a: "1" if h > a else ("2" if a > h else "X")
    for h1 in range(n):
        for a1 in range(n):
            for h2 in range(n):
                for a2 in range(n):
                    htft[f"{sym(h1, a1)}/{sym(h1 + h2, a1 + a2)}"] += M1[h1, a1] * M2[h2, a2]
    htft = {k: round(v * 100, 1) for k, v in htft.items()}
    best = max(htft, key=htft.get)
    markets["ht_ft"] = {"prediction": best, "confidence": f"{htft[best]:.1f}%",
                        "options": dict(sorted(htft.items(), key=lambda x: -x[1])[:4])}

    # 10. 3-way handicap, home -1
    diff = np.subtract.outer(np.arange(M.shape[0]), np.arange(M.shape[1]))
    hcp = {"1 (-1)": round(float(M[diff >= 2].sum()) * 100, 1),
           "X (-1)": round(float(M[diff == 1].sum()) * 100, 1),
           "2 (-1)": round(float(M[diff <= 0].sum()) * 100, 1)}
    markets["handicap"] = {"prediction": max(hcp, key=hcp.get), "confidence": f"{max(hcp.values()):.1f}%",
                           "options": hcp}

    # 11-14. Halves
    for key, H in [("h1", M1), ("h2", M2)]:
        p3 = outcome_probs(H)
        pick_h, p_h = _pick_1x2(p3)
        markets[f"1x2_{key}"] = {"prediction": pick_h, "confidence": f"{p_h * 100:.1f}%",
                                 "options": {"1": round(p3[0] * 100, 1), "X": round(p3[1] * 100, 1),
                                             "2": round(p3[2] * 100, 1)}}
        pk, cf = _fmt_ou(*_ou(H, 0.5), 0.5)
        markets[f"ou_{key}"] = {"prediction": pk, "confidence": f"{cf:.1f}%",
                                "all_thresholds": _thresholds(lambda l, H=H: _ou(H, l), [0.5, 1.5, 2.5])}

    return markets, correct_scores(M), {"home_xg": round(lam, 2), "away_xg": round(mu, 2), "rho": round(rho, 3)}


def best_correct_scores(home_xg, away_xg, n=5, rho=0.0):
    return correct_scores(score_matrix(home_xg, away_xg, rho), n)
