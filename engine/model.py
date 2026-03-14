from engine.poisson import all_markets
from engine.stats import get_team_stats

def _build_reasoning(analysis, markets, home_team, away_team, team_stats):
    """
    Generate a human-readable explanation of the prediction.
    """
    reasons = []
    m      = markets
    net    = analysis.get("net_score", 0)
    form   = analysis.get("form_differential", 0)
    vol    = analysis.get("text_volume", 0)
    src    = (team_stats or {}).get("data_source", "nlp_fallback")

    # Data source note
    if src == "known_db":
        reasons.append(f"📊 Real 2024/25 season stats used for both teams.")
    elif src == "web_extracted":
        reasons.append(f"🌐 Live web stats extracted for prediction.")
    else:
        reasons.append(f"⚠️ Using league averages — no specific team data found.")

    # Attack/defense context
    h_atk  = (team_stats or {}).get("home_attack")
    a_atk  = (team_stats or {}).get("away_attack")
    h_def  = (team_stats or {}).get("home_defense")
    a_def  = (team_stats or {}).get("away_defense")

    if h_atk and a_def:
        if h_atk > 1.8:
            reasons.append(f"⚡ {home_team} is a strong attacking side ({h_atk:.2f} goals/game).")
        if a_def > 1.4:
            reasons.append(f"🔓 {away_team} has a leaky defense ({a_def:.2f} conceded/game).")
    if a_atk and h_def:
        if a_atk > 1.8:
            reasons.append(f"⚡ {away_team} scores freely ({a_atk:.2f} goals/game).")
        if h_def > 1.4:
            reasons.append(f"🔓 {home_team} has a leaky defense ({h_def:.2f} conceded/game).")

    # xG summary
    meta = markets.get("_meta", {})
    xg_h = meta.get("home_xg"); xg_a = meta.get("away_xg")
    if xg_h and xg_a:
        dominant = home_team if xg_h > xg_a else away_team
        reasons.append(f"🎯 Model xG: {home_team} {xg_h:.2f} — {away_team} {xg_a:.2f}. {dominant} expected to dominate.")

    # NLP signals
    if vol > 0:
        if net > 3:
            reasons.append(f"📰 News & previews strongly favour {home_team}.")
        elif net < -3:
            reasons.append(f"📰 News & previews strongly favour {away_team}.")
        if form > 5:
            reasons.append(f"📈 {home_team} in excellent recent form.")
        elif form < -5:
            reasons.append(f"📈 {away_team} in excellent recent form.")

    # BTTS note
    btts = markets.get("btts", {})
    if btts.get("prediction") == "YES" and float(btts.get("confidence","0%").strip("%")) > 55:
        reasons.append("⚽ Both teams likely to score based on goal-scoring patterns.")

    return " ".join(reasons) if reasons else "Prediction based on statistical model."


def _find_best_bet(markets):
    """
    Scan all markets and return the single highest-confidence pick.
    Excludes meta-key, correct scores. Returns (market_name, pick, confidence_float).
    """
    SKIP = {"_meta", "boosted"}  # boosted is derived, not independent
    best_conf = 0.0
    best_label = ""
    best_pick  = ""

    LABELS = {
        "1x2_ft":       "1X2 Full Time",
        "double_chance": "Double Chance",
        "btts":         "BTTS",
        "ou_ft":        "Over/Under FT",
        "handicap":     "3-Way Handicap",
        "1x2_h1":       "1X2 1st Half",
        "1x2_h2":       "1X2 2nd Half",
        "ou_h1":        "O/U 1st Half",
        "ou_h2":        "O/U 2nd Half",
        "ou_home":      "Home O/U",
        "ou_away":      "Away O/U",
        "next_goal":    "Next Goal",
        "ht_ft":        "HT/FT",
    }

    for key, m in markets.items():
        if key in SKIP or not isinstance(m, dict):
            continue
        conf_str = m.get("confidence", "0%")
        try:
            conf = float(conf_str.replace("%", ""))
        except Exception:
            continue
        if conf > best_conf:
            best_conf  = conf
            best_pick  = m.get("prediction", "")
            best_label = LABELS.get(key, key)

    return best_label, best_pick, best_conf


def predict_match(analysis, home_team="", away_team=""):
    """
    Main prediction function.
    Integrates real team stats → Poisson → 14 markets + best bet + reasoning.
    """
    # 1. Fetch real team statistics
    print(f"  [Model] Fetching stats for {home_team} vs {away_team}...")
    team_stats = get_team_stats(home_team, away_team, use_web_fallback=True)
    print(f"  [Model] Data source: {team_stats['data_source']} | "
          f"xG base: H {team_stats['home_attack']:.2f} / A {team_stats['away_attack']:.2f}")

    # 2. Derive all 14 markets using upgraded Poisson engine
    markets, correct_scores, metadata = all_markets(
        analysis, home_team, away_team, team_stats=team_stats
    )

    # Inject metadata into markets dict for reasoning builder
    markets["_meta"] = metadata

    # 3. Injury adjustment indicator
    inj = analysis.get("injury_adjustment", 0)

    # 4. Confidence scoring — now based on data quality + signal strength
    net_score  = abs(analysis.get("net_score", 0))
    vol        = analysis.get("text_volume", 0)
    src        = team_stats.get("data_source", "nlp_fallback")

    if src == "known_db" and net_score >= 3 and vol >= 3:
        confidence = "HIGH"
    elif src in ("known_db", "web_extracted") and (net_score >= 1 or vol >= 1):
        confidence = "MEDIUM"
    elif src == "known_db":
        confidence = "MEDIUM"   # At least we have real stats
    else:
        confidence = "LOW"

    # If metadata shows stats-driven, bump Medium → High for display clarity
    if metadata.get("stats_driven") and net_score >= 5 and vol >= 5:
        confidence = "HIGH"

    # 5. Build human-readable reasoning
    reasoning = _build_reasoning(analysis, markets, home_team, away_team, team_stats)

    # 6. Best bet across all markets
    best_label, best_pick, best_conf = _find_best_bet(markets)

    # 7. Clean up internal meta key before returning
    markets.pop("_meta", None)

    return {
        "status":           "success",
        "home":             home_team,
        "away":             away_team,
        "overall_confidence": confidence,
        "markets":          markets,
        "correct_scores":   correct_scores,
        "analysis_meta":    metadata,
        "best_bet": {
            "market":     best_label,
            "pick":       best_pick,
            "confidence": f"{best_conf:.1f}%"
        },
        "reasoning":        reasoning,
        "team_stats":       {
            "home_attack":  team_stats["home_attack"],
            "home_defense": team_stats["home_defense"],
            "away_attack":  team_stats["away_attack"],
            "away_defense": team_stats["away_defense"],
            "data_source":  team_stats["data_source"],
        },
        # Legacy compatibility
        "score":        analysis.get("net_score", 0),
        "draw_signals": analysis.get("draw_signals", 0),
    }
