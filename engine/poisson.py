import math

def _poisson_pmf(k, lam):
    """Calculate the Poisson probability mass function P(X=k)."""
    if lam <= 0: return 0
    return (lam**k * math.exp(-lam)) / math.factorial(k)

def score_matrix(home_xg, away_xg, max_goals=8):
    """
    Generate a 2D matrix of probabilities for every exact scoreline.
    M[h][a] = probability of home scoring h and away scoring a.
    """
    matrix = [[0.0 for _ in range(max_goals)] for _ in range(max_goals)]
    for h in range(max_goals):
        for a in range(max_goals):
            matrix[h][a] = _poisson_pmf(h, home_xg) * _poisson_pmf(a, away_xg)
    return matrix

def _market_1x2(matrix):
    """1X2 Market probabilities."""
    home_win, draw, away_win = 0.0, 0.0, 0.0
    for h in range(len(matrix)):
        for a in range(len(matrix[0])):
            prob = matrix[h][a]
            if h > a:   home_win += prob
            elif h == a: draw    += prob
            else:        away_win += prob
    return home_win, draw, away_win

def _market_btts(matrix):
    """Both Teams To Score probabilities."""
    btts_yes = 0.0
    for h in range(1, len(matrix)):
        for a in range(1, len(matrix[0])):
            btts_yes += matrix[h][a]
    return btts_yes, 1.0 - btts_yes

def _market_over_under(matrix, threshold):
    """Over/Under threshold probabilities."""
    under, over = 0.0, 0.0
    for h in range(len(matrix)):
        for a in range(len(matrix[0])):
            if (h + a) > threshold: over  += matrix[h][a]
            else:                   under += matrix[h][a]
    return over, under

def _market_team_ou(xg, threshold):
    """Over/Under threshold for a single team based on its xG."""
    under = 0.0
    for k in range(int(threshold + 1)):
        under += _poisson_pmf(k, xg)
    return 1.0 - under, under  # over, under

def _correct_scores(matrix):
    """Extract and sort correct score probabilities."""
    scores = []
    for h in range(len(matrix)):
        for a in range(len(matrix[0])):
            if matrix[h][a] > 0.005:
                scores.append({"score": f"{h} - {a}", "prob": round(matrix[h][a] * 100, 2)})
    return sorted(scores, key=lambda x: x["prob"], reverse=True)


def all_markets(analysis, home_team="", away_team="", team_stats=None):
    """
    Derives all 14 betting markets.
    NOW uses Dixon-Coles xG when real team_stats are provided.
    NLP sentiment is used as a secondary modifier (capped at ±15%).
    """
    net_score     = analysis.get("net_score", 0)
    form_diff     = analysis.get("form_differential", 0)
    inj_adj       = analysis.get("injury_adjustment", 0)  # NEW: injury impact

    # ── XG CALCULATION ────────────────────────────────────────────────────────
    if team_stats and team_stats.get("home_attack"):
        # Primary: Dixon-Coles / real stats based xG (imported inline to avoid circular)
        from engine.stats import compute_dixon_coles_xg
        xg_h, xg_a = compute_dixon_coles_xg(team_stats)

        # Secondary: NLP sentiment modifier — capped at ±20% of xG
        nlp_mod_h =  (net_score * 0.04) + (form_diff * 0.02)
        nlp_mod_a = -(net_score * 0.04) - (form_diff * 0.02)
        max_mod = xg_h * 0.20
        nlp_mod_h = max(-max_mod, min(nlp_mod_h, max_mod))
        nlp_mod_a = max(-xg_a * 0.20, min(nlp_mod_a, xg_a * 0.20))

        xg_h = max(0.3, xg_h + nlp_mod_h + inj_adj)
        xg_a = max(0.2, xg_a + nlp_mod_a - inj_adj)
        stats_driven = True
    else:
        # Fallback: pure NLP (old behaviour)
        base_xg_h = 1.48
        base_xg_a = 1.17
        xg_h = max(0.3, base_xg_h + (net_score * 0.1) + (form_diff * 0.05))
        xg_a = max(0.2, base_xg_a - (net_score * 0.1) - (form_diff * 0.05))
        stats_driven = False

    # Round for display
    xg_h = round(xg_h, 2)
    xg_a = round(xg_a, 2)

    # Generate matrices
    M_ft = score_matrix(xg_h, xg_a, 8)
    M_h1 = score_matrix(xg_h * 0.44, xg_a * 0.44, 6)
    M_h2 = score_matrix(xg_h * 0.56, xg_a * 0.56, 6)

    markets = {}

    # Helper
    def format_ou(over, under, line):
        if over > under: return "OVER "  + str(line), over  * 100
        return             "UNDER " + str(line), under * 100

    # ── 1. 1X2 Full Time ──────────────────────────────────────────────────────
    hw, dr, aw = _market_1x2(M_ft)
    if hw > dr and hw > aw:   pick_1x2, conf_1x2 = "HOME WIN", hw * 100
    elif aw > hw and aw > dr: pick_1x2, conf_1x2 = "AWAY WIN", aw * 100
    else:                     pick_1x2, conf_1x2 = "DRAW",     dr * 100

    markets["1x2_ft"] = {
        "prediction": pick_1x2,
        "confidence": f"{conf_1x2:.1f}%",
        "options": {"1": round(hw*100,1), "X": round(dr*100,1), "2": round(aw*100,1)}
    }

    # ── 2. Boosted Pick ───────────────────────────────────────────────────────
    if pick_1x2 != "DRAW" and conf_1x2 > 52:
        markets["boosted"] = {"prediction": pick_1x2, "confidence": f"{min(conf_1x2 + 4, 97):.1f}%"}
    else:
        o_ft, _ = _market_over_under(M_ft, 1.5)
        markets["boosted"] = {"prediction": "OVER 1.5", "confidence": f"{o_ft*100:.1f}%"}

    # ── 3. Double Chance ──────────────────────────────────────────────────────
    hw_dr = hw + dr; aw_dr = aw + dr; hw_aw = hw + aw
    opts_dc = {"1X": round(hw_dr*100,1), "X2": round(aw_dr*100,1), "12": round(hw_aw*100,1)}
    best_dc = max(opts_dc, key=opts_dc.get)
    markets["double_chance"] = {
        "prediction": best_dc + " DC",
        "confidence": f"{opts_dc[best_dc]:.1f}%",
        "options": opts_dc
    }

    # ── 4. BTTS ───────────────────────────────────────────────────────────────
    btts_y, btts_n = _market_btts(M_ft)
    markets["btts"] = {
        "prediction": "YES" if btts_y > btts_n else "NO",
        "confidence": f"{max(btts_y, btts_n)*100:.1f}%",
        "options": {"YES": round(btts_y*100,1), "NO": round(btts_n*100,1)}
    }

    # ── 5. Next Goal ──────────────────────────────────────────────────────────
    p_00 = M_ft[0][0]
    prob_goal = 1.0 - p_00
    sum_xg = xg_h + xg_a
    h_first = prob_goal * (xg_h / sum_xg) if sum_xg > 0 else 0
    a_first = prob_goal * (xg_a / sum_xg) if sum_xg > 0 else 0
    opts_ng = {"Home": round(h_first*100,1), "Away": round(a_first*100,1), "None": round(p_00*100,1)}
    markets["next_goal"] = {
        "prediction": max(opts_ng, key=opts_ng.get),
        "confidence": f"{max(opts_ng.values()):.1f}%",
        "options": opts_ng
    }

    # ── 6. Over/Under FT ──────────────────────────────────────────────────────
    o_ft_25, u_ft_25 = _market_over_under(M_ft, 2.5)
    pick_ou_ft, conf_ou_ft = format_ou(o_ft_25, u_ft_25, 2.5)
    all_ou_ft = []
    for line in [0.5, 1.5, 2.5, 3.5]:
        ov, un = _market_over_under(M_ft, line)
        lbl = "O" if ov > un else "U"
        all_ou_ft.append({"pick": "OVER" if ov > un else "UNDER",
                          "label": f"{lbl}{line}", "confidence": round(max(ov,un)*100,1)})
    markets["ou_ft"] = {"prediction": pick_ou_ft, "confidence": f"{conf_ou_ft:.1f}%", "all_thresholds": all_ou_ft}

    # ── 7 & 8. O/U Home & Away ───────────────────────────────────────────────
    for side, team, xg in [("home", home_team, xg_h), ("away", away_team, xg_a)]:
        ov, un = _market_team_ou(xg, 1.5)
        pick_ou, conf_ou = format_ou(ov, un, 1.5)
        all_ou = []
        for line in [0.5, 1.5, 2.5]:
            ov_l, un_l = _market_team_ou(xg, line)
            lbl = "O" if ov_l > un_l else "U"
            all_ou.append({"pick": "OVER" if ov_l > un_l else "UNDER",
                          "label": f"{lbl}{line}", "confidence": round(max(ov_l,un_l)*100,1)})
        markets[f"ou_{side}"] = {
            "prediction": pick_ou, "confidence": f"{conf_ou:.1f}%",
            "all_thresholds": all_ou, "label": f"{team} O/U | FT"
        }

    # ── 9. HT/FT (strict convolution) ────────────────────────────────────────
    opts_htft = {f"{a}/{b}": 0.0 for a in "1X2" for b in "1X2"}
    for h1 in range(5):
        for a1 in range(5):
            prob1 = M_h1[h1][a1]
            ht_sym = "1" if h1 > a1 else ("2" if a1 > h1 else "X")
            for h2 in range(5):
                for a2 in range(5):
                    prob2 = M_h2[h2][a2]
                    h_ft, a_ft = h1+h2, a1+a2
                    ft_sym = "1" if h_ft > a_ft else ("2" if a_ft > h_ft else "X")
                    opts_htft[f"{ht_sym}/{ft_sym}"] += (prob1 * prob2)
    for k in opts_htft: opts_htft[k] = round(opts_htft[k] * 100, 1)
    best_htft = max(opts_htft, key=opts_htft.get)
    sorted_htft = sorted(opts_htft.items(), key=lambda x: x[1], reverse=True)[:4]
    markets["ht_ft"] = {"prediction": best_htft, "confidence": f"{opts_htft[best_htft]:.1f}%",
                        "options": dict(sorted_htft)}

    # ── 10. 3-Way Handicap (Home -1) ─────────────────────────────────────────
    hw_hcp = dr_hcp = aw_hcp = 0.0
    for h in range(len(M_ft)):
        for a in range(len(M_ft[0])):
            h_adj = h - 1
            if h_adj > a:    hw_hcp += M_ft[h][a]
            elif h_adj == a: dr_hcp += M_ft[h][a]
            else:            aw_hcp += M_ft[h][a]
    opts_hcp = {"1 (-1)": round(hw_hcp*100,1), "X (-1)": round(dr_hcp*100,1), "2 (-1)": round(aw_hcp*100,1)}
    markets["handicap"] = {"prediction": max(opts_hcp, key=opts_hcp.get),
                           "confidence": f"{max(opts_hcp.values()):.1f}%", "options": opts_hcp}

    # ── 11 & 12. 1X2 First / Second Half ─────────────────────────────────────
    for ht_str, ht_M in [("h1", M_h1), ("h2", M_h2)]:
        hht, dht, aht = _market_1x2(ht_M)
        if hht > dht and hht > aht:   best_ht, conf_ht = "HOME WIN", hht
        elif aht > hht and aht > dht: best_ht, conf_ht = "AWAY WIN", aht
        else:                         best_ht, conf_ht = "DRAW",     dht
        markets[f"1x2_{ht_str}"] = {
            "prediction": best_ht, "confidence": f"{conf_ht*100:.1f}%",
            "options": {"1": round(hht*100,1), "X": round(dht*100,1), "2": round(aht*100,1)}
        }

    # ── 13 & 14. O/U First / Second Half ─────────────────────────────────────
    for ht_str, ht_M in [("h1", M_h1), ("h2", M_h2)]:
        o_ht, u_ht = _market_over_under(ht_M, 0.5)
        pick_ou, conf_ou = format_ou(o_ht, u_ht, 0.5)
        all_ou = []
        for line in [0.5, 1.5, 2.5]:
            ov_l, un_l = _market_over_under(ht_M, line)
            lbl = "O" if ov_l > un_l else "U"
            all_ou.append({"pick": "OVER" if ov_l > un_l else "UNDER",
                          "label": f"{lbl}{line}", "confidence": round(max(ov_l,un_l)*100,1)})
        markets[f"ou_{ht_str}"] = {"prediction": pick_ou, "confidence": f"{conf_ou:.1f}%",
                                   "all_thresholds": all_ou}

    correct_scores = _correct_scores(M_ft)[:6]

    return markets, correct_scores, {
        "home_xg": xg_h,
        "away_xg": xg_a,
        "stats_driven": stats_driven,
        "data_source": (team_stats or {}).get("data_source", "nlp_fallback")
    }


def best_correct_scores(home_xg, away_xg, n=5):
    """Utility: return top-N most probable correct scores."""
    M = score_matrix(home_xg, away_xg, 8)
    return _correct_scores(M)[:n]
