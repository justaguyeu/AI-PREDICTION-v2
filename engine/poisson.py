import math

def _poisson_pmf(k, lam):
    """Calculate the Poisson probability mass function P(X=k)."""
    if lam < 0: return 0
    return (lam**k * math.exp(-lam)) / math.factorial(k)

def score_matrix(home_xg, away_xg, max_goals=8):
    """
    Generate a 2D matrix of probabilities for every exact scoreline up to (max_goals-1).
    M[h][a] represents probability of home scoring h and away scoring a.
    Returns: a list of lists.
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
            if h > a:
                home_win += prob
            elif h == a:
                draw += prob
            else:
                away_win += prob
    return home_win, draw, away_win

def _market_btts(matrix):
    """Both Teams To Score probabilities."""
    btts_yes = 0.0
    for h in range(1, len(matrix)):
        for a in range(1, len(matrix[0])):
            btts_yes += matrix[h][a]
    return btts_yes, 1.0 - btts_yes

def _market_over_under(matrix, threshold):
    """Over/Under exactly threshold probabilities."""
    under, over = 0.0, 0.0
    for h in range(len(matrix)):
        for a in range(len(matrix[0])):
            if (h + a) > threshold:
                over += matrix[h][a]
            else:
                under += matrix[h][a]
    return over, under

def _market_team_ou(xg, threshold):
    """Over/Under threshold for a single team based on its total xG."""
    under = 0.0
    for k in range(int(threshold + 1)):  # up to floor(threshold)
        under += _poisson_pmf(k, xg)
    return 1.0 - under, under  # over, under

def _correct_scores(matrix):
    """Extract and sort correct score probabilities."""
    scores = []
    for h in range(len(matrix)):
        for a in range(len(matrix[0])):
            if matrix[h][a] > 0.005: # Optimization: skip practically impossible scores
                scores.append({"score": f"{h} - {a}", "prob": matrix[h][a] * 100})
    return sorted(scores, key=lambda x: x["prob"], reverse=True)

def all_markets(analysis, home_team="", away_team=""):
    """
    Derives all 14 betting markets from the analysis sentiment and base stats.
    Returns a dictionary of market predictions.
    """
    # ── BASELINE XG CALCULATION ──
    # Map sentiments or raw stats to base expected goals.
    # A generic implementation if actual team data is missing.
    base_xg_h = 1.35
    base_xg_a = 1.05

    # Adjust xG using provided analysis numbers (sentiments, goals_for/against, etc.)
    # E.g. If net_score is very positive, home team has an advantage
    net_score = analysis.get("net_score", 0)
    xg_h = max(0.2, base_xg_h + (net_score * 0.1))
    xg_a = max(0.2, base_xg_a - (net_score * 0.1))

    # Form adjustment
    form_diff = analysis.get("form_differential", 0)
    xg_h = max(0.2, xg_h + (form_diff * 0.05))
    xg_a = max(0.2, xg_a - (form_diff * 0.05))

    # Generate Full Time Matrix
    M_ft = score_matrix(xg_h, xg_a, 8)
    
    # Generate Half Time Matrices (approx 45% and 55% of xG)
    M_h1 = score_matrix(xg_h * 0.45, xg_a * 0.45, 6)
    M_h2 = score_matrix(xg_h * 0.55, xg_a * 0.55, 6)

    markets = {}

    # 1. 1X2 Full Time
    hw, dr, aw = _market_1x2(M_ft)
    if hw > dr and hw > aw:
        pick_1x2 = "HOME WIN"
        conf_1x2 = hw * 100
    elif aw > hw and aw > dr:
        pick_1x2 = "AWAY WIN"
        conf_1x2 = aw * 100
    else:
        pick_1x2 = "DRAW"
        conf_1x2 = dr * 100
    
    markets["1x2_ft"] = {
        "prediction": pick_1x2,
        "confidence": f"{conf_1x2:.1f}%",
        "options": {"1": round(hw*100,1), "X": round(dr*100,1), "2": round(aw*100,1)}
    }

    # 2. Boosted (Safe bet recommendation)
    if pick_1x2 != "DRAW" and conf_1x2 > 50:
        markets["boosted"] = {"prediction": pick_1x2, "confidence": f"{(conf_1x2 + 5):.1f}%"}
    else:
        o_ft, _ = _market_over_under(M_ft, 1.5)
        markets["boosted"] = {"prediction": "OVER 1.5", "confidence": f"{(o_ft*100):.1f}%"}

    # 3. Double Chance
    hw_dr = hw + dr
    aw_dr = aw + dr
    hw_aw = hw + aw
    options_dc = {"1X": round(hw_dr*100,1), "X2": round(aw_dr*100,1), "12": round(hw_aw*100,1)}
    best_dc = max(options_dc, key=options_dc.get)
    markets["double_chance"] = {
        "prediction": best_dc + " DC",
        "confidence": f"{options_dc[best_dc]:.1f}%",
        "options": options_dc
    }

    # 4. BTTS
    btts_y, btts_n = _market_btts(M_ft)
    markets["btts"] = {
        "prediction": "YES" if btts_y > btts_n else "NO",
        "confidence": f"{(max(btts_y, btts_n) * 100):.1f}%",
        "options": {"YES": round(btts_y*100,1), "NO": round(btts_n*100,1)}
    }

    # 5. Next Goal (Goal 1)
    p_00_ft = M_ft[0][0]
    prob_goal = 1.0 - p_00_ft
    # If a goal happens, probability of team scoring first is approx proportional to xG
    if prob_goal > 0.01:
        sum_xg = xg_h + xg_a
        h_first = prob_goal * (xg_h / sum_xg)
        a_first = prob_goal * (xg_a / sum_xg)
    else:
        h_first, a_first = 0, 0
    opts_ng = {"Home": round(h_first*100,1), "Away": round(a_first*100,1), "None": round(p_00_ft*100,1)}
    best_ng = max(opts_ng, key=opts_ng.get)
    markets["next_goal"] = {
        "prediction": best_ng,
        "confidence": f"{opts_ng[best_ng]:.1f}%",
        "options": opts_ng
    }

    # Helper for OU markets
    def format_ou(over, under, line):
        if over > under: return "OVER " + str(line), over * 100
        return "UNDER " + str(line), under * 100

    # 6. Over/Under FT
    o_ft_25, u_ft_25 = _market_over_under(M_ft, 2.5)
    pick_ou_ft, conf_ou_ft = format_ou(o_ft_25, u_ft_25, 2.5)
    all_ou_ft = []
    for line in [0.5, 1.5, 2.5, 3.5]:
        ov, un = _market_over_under(M_ft, line)
        if ov > un: all_ou_ft.append({"pick": "OVER", "label": f"O{line}", "confidence": round(ov*100,1)})
        else: all_ou_ft.append({"pick": "UNDER", "label": f"U{line}", "confidence": round(un*100,1)})
    markets["ou_ft"] = {"prediction": pick_ou_ft, "confidence": f"{conf_ou_ft:.1f}%", "all_thresholds": all_ou_ft}

    # 7 & 8. Over/Under Home & Away
    for side, team, xg in [("home", home_team, xg_h), ("away", away_team, xg_a)]:
        ov, un = _market_team_ou(xg, 1.5)
        pick_ou, conf_ou = format_ou(ov, un, 1.5)
        all_ou = []
        for line in [0.5, 1.5, 2.5]:
            ov_l, un_l = _market_team_ou(xg, line)
            if ov_l > un_l: all_ou.append({"pick": "OVER", "label": f"O{line}", "confidence": round(ov_l*100,1)})
            else: all_ou.append({"pick": "UNDER", "label": f"U{line}", "confidence": round(un_l*100,1)})
        markets[f"ou_{side}"] = {"prediction": pick_ou, "confidence": f"{conf_ou:.1f}%", "all_thresholds": all_ou, "label": f"{team} O/U | FT"}

    # 9. HT/FT (Combining h1 and h2 independently)
    hw1, dr1, aw1 = _market_1x2(M_h1)
    # Using full time matrix for 2nd half of the notation (the FT outcome)
    # Approximation via independent halves: P(HT) * P(H2)
    opts_htft = {}
    h1_states = {"1": hw1, "X": dr1, "2": aw1}
    # To get FT state accurately, we iterate H1 and H2 score states.
    # Simplified approximation for speed:
    for s1, p1 in h1_states.items():
        # What is the conditional prob of FT outcome given H1?
        # We assume H1 result correlates loosely with FT result.
        # Strict calculation requires convoluting M_h1 and M_h2.
        for s2, _ in h1_states.items():
            key = f"{s1}/{s2}"
            opts_htft[key] = 0.0

    # Strict convolution
    for h1 in range(5):
        for a1 in range(5):
            prob1 = M_h1[h1][a1]
            ht_sym = "1" if h1 > a1 else "2" if a1 > h1 else "X"
            for h2 in range(5):
                for a2 in range(5):
                    prob2 = M_h2[h2][a2]
                    h_ft, a_ft = h1 + h2, a1 + a2
                    ft_sym = "1" if h_ft > a_ft else "2" if a_ft > h_ft else "X"
                    opts_htft[f"{ht_sym}/{ft_sym}"] += (prob1 * prob2)
    
    # Format
    for k in opts_htft: opts_htft[k] = round(opts_htft[k] * 100, 1)
    best_htft = max(opts_htft, key=opts_htft.get)
    # Keep only top 4 for UI size
    sorted_htft = sorted(opts_htft.items(), key=lambda x:x[1], reverse=True)[:4]
    markets["ht_ft"] = {"prediction": best_htft, "confidence": f"{opts_htft[best_htft]:.1f}%", "options": dict(sorted_htft)}

    # 10. 3-Way Handicap FT (Home -1)
    hw_hcp, dr_hcp, aw_hcp = 0.0, 0.0, 0.0
    for h in range(len(M_ft)):
        for a in range(len(M_ft[0])):
            h_adj = h - 1  # Home -1 handicap
            if h_adj > a: hw_hcp += M_ft[h][a]
            elif h_adj == a: dr_hcp += M_ft[h][a]
            else: aw_hcp += M_ft[h][a]
    opts_hcp = {"1 (-1)": round(hw_hcp*100,1), "X (-1)": round(dr_hcp*100,1), "2 (-1)": round(aw_hcp*100,1)}
    best_hcp = max(opts_hcp, key=opts_hcp.get)
    markets["handicap"] = {"prediction": best_hcp, "confidence": f"{opts_hcp[best_hcp]:.1f}%", "options": opts_hcp}

    # 11 & 12. 1X2 First / Second Half
    for ht_str, ht_M in [("h1", M_h1), ("h2", M_h2)]:
        hht, dht, aht = _market_1x2(ht_M)
        if hht > dht and hht > aht: best_ht = "HOME WIN"; conf_ht = hht
        elif aht > hht and aht > dht: best_ht = "AWAY WIN"; conf_ht = aht
        else: best_ht = "DRAW"; conf_ht = dht
        markets[f"1x2_{ht_str}"] = {
            "prediction": best_ht,
            "confidence": f"{(conf_ht*100):.1f}%",
            "options": {"1": round(hht*100,1), "X": round(dht*100,1), "2": round(aht*100,1)}
        }

    # 13 & 14. Over/Under First / Second Half
    for ht_str, ht_M in [("h1", M_h1), ("h2", M_h2)]:
        o_ht, u_ht = _market_over_under(ht_M, 1.5)
        pick_ou, conf_ou = format_ou(o_ht, u_ht, 1.5)
        all_ou = []
        for line in [0.5, 1.5, 2.5]:
            ov_l, un_l = _market_over_under(ht_M, line)
            if ov_l > un_l: all_ou.append({"pick": "OVER", "label": f"O{line}", "confidence": round(ov_l*100,1)})
            else: all_ou.append({"pick": "UNDER", "label": f"U{line}", "confidence": round(un_l*100,1)})
        markets[f"ou_{ht_str}"] = {"prediction": pick_ou, "confidence": f"{conf_ou:.1f}%", "all_thresholds": all_ou}

    # Get Correct Scores
    correct_scores = _correct_scores(M_ft)[:5]

    return markets, correct_scores, {"home_xg": round(xg_h, 2), "away_xg": round(xg_a, 2)}
