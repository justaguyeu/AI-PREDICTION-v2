import re

def extract_form_score(text, team_name):
    """Extract form score from W-D-L patterns (e.g., WWDWL = +5)"""
    team = team_name.lower()
    form_score = 0
    
    # Look for form patterns like "WWDWL" or "W-W-D-W-L"
    form_patterns = re.findall(rf"{team}.*?form[:\s]+([wdl\-\s]+)", text, re.IGNORECASE)
    for pattern in form_patterns:
        clean_pattern = pattern.upper().replace('-', '').replace(' ', '')[:5]  # Last 5 games
        for char in clean_pattern:
            if char == 'W': form_score += 3
            elif char == 'D': form_score += 1
            # L = 0 points
    
    # Look for explicit mentions like "won last 3" or "unbeaten in 5"
    if re.search(rf"{team}.*?(won|winning).{{0,10}}(last|past).{{0,5}}(\d+)", text):
        match = re.search(rf"{team}.*?(won|winning).{{0,10}}(last|past).{{0,5}}(\d+)", text)
        if match:
            wins = int(match.group(3))
            form_score += wins * 2  # Bonus for winning streaks
    
    if re.search(rf"{team}.*?unbeaten.{{0,10}}(\d+)", text):
        match = re.search(rf"{team}.*?unbeaten.{{0,10}}(\d+)", text)
        if match:
            unbeaten = int(match.group(1))
            form_score += unbeaten * 1.5
    
    return form_score


def extract_goals_stats(text, team_name):
    """Extract goals scored and conceded from text"""
    team = team_name.lower()
    goals_for = []
    goals_against = []
    
    # Look for patterns like "scored 15 goals" or "conceded 8"
    scored_patterns = re.findall(rf"{team}.*?scored.{{0,10}}(\d+)", text)
    goals_for.extend([int(g) for g in scored_patterns])
    
    conceded_patterns = re.findall(rf"{team}.*?conceded.{{0,10}}(\d+)", text)
    goals_against.extend([int(g) for g in conceded_patterns])
    
    # Look for "averaging X goals per game"
    avg_patterns = re.findall(rf"{team}.*?averaging.{{0,10}}(\d+\.?\d*).{{0,10}}goals", text)
    if avg_patterns:
        goals_for.extend([float(g) for g in avg_patterns])
    
    return {
        'goals_for': sum(goals_for) / len(goals_for) if goals_for else None,
        'goals_against': sum(goals_against) / len(goals_against) if goals_against else None
    }


def extract_recent_results(text, team_name):
    """Extract recent match results and scores"""
    team = team_name.lower()
    results = []
    
    # Look for patterns like "won 3-1" or "lost 0-2" or "drew 1-1"
    result_patterns = re.findall(
        rf"{team}.*?(won|lost|drew).{{0,15}}(\d+)-(\d+)", 
        text
    )
    
    for result_type, score1, score2 in result_patterns:
        h, a = int(score1), int(score2)
        if h + a < 10:  # Sanity check
            results.append({
                'result': result_type,
                'goals_for': h,
                'goals_against': a
            })
    
    return results


def analyze_text(categorized_texts, home_team, away_team):
    # categorized_texts is expected to be a dict: {'prediction': [texts], 'form': [texts], ...}
    # Backward compatibility: if it's a list, treat it as 'preview'
    if isinstance(categorized_texts, list):
        categorized_texts = {"preview": categorized_texts}

    home = home_team.lower()
    away = away_team.lower()

    # Scores
    sentiment_prediction = 0
    sentiment_form = 0
    sentiment_news = 0
    sentiment_preview = 0
    
    total_text_len = 0
    all_combined_text = ""
    
    # 1. Analyze Predictions (Extract Scores)
    valid_scores = []
    # Map 'tactical_edge' and 'market_sentiment' to prediction logic
    texts_pred = categorized_texts.get("prediction", []) + categorized_texts.get("tactical_edge", []) + categorized_texts.get("market_sentiment", [])
    if texts_pred:
        combined_pred = " ".join(texts_pred).lower()
        total_text_len += len(texts_pred)
        all_combined_text += combined_pred
        
        # Regex Score Extraction
        all_scores_regex = re.findall(r"\b(\d{1,2})-(\d{1,2})\b", combined_pred)
        for h_s, a_s in all_scores_regex:
            h = int(h_s)
            a = int(a_s)
            if h + a < 10 and not (h==0 and a==0):
                valid_scores.append((h, a))
        
        # Weigh scores
        for h, a in valid_scores:
            if h > a: sentiment_prediction += 3
            elif a > h: sentiment_prediction -= 3
            else: pass # Draw handled in model

    # 2. Analyze Form (Unbeaten, Winning Streak)
    # Map 'h2h_context' to form logic
    texts_form = categorized_texts.get("form", []) + categorized_texts.get("h2h_context", [])
    if texts_form:
        combined_form = " ".join(texts_form).lower()
        total_text_len += len(texts_form)
        all_combined_text += combined_form
        
        if re.search(rf"{home}.*?(unbeaten|winning streak|excellent form|won \d)", combined_form):
            sentiment_form += 3
        if re.search(rf"{away}.*?(unbeaten|winning streak|excellent form|won \d)", combined_form):
            sentiment_form -= 3
        
        # Enhanced Negative Detection
        if re.search(rf"{home}.*?(poor form|losing streak|no wins|struggling|relegation|bottom)", combined_form):
            sentiment_form -= 2
        if re.search(rf"{away}.*?(poor form|losing streak|no wins|struggling|relegation|bottom)", combined_form):
            sentiment_form += 2

    # 3. Analyze News (Injuries)
    # Map 'injury_deep_dive' to news logic
    texts_news = categorized_texts.get("news", []) + categorized_texts.get("injury_deep_dive", [])
    if texts_news:
        combined_news = " ".join(texts_news).lower()
        total_text_len += len(texts_news)
        all_combined_text += combined_news
        
        # Missing key players is bad
        if re.search(rf"{home}.*?(missing|out|suspended|injured).{{0,30}}(key|captain|striker|star)", combined_news):
            sentiment_news -= 3
        if re.search(rf"{away}.*?(missing|out|suspended|injured).{{0,30}}(key|captain|striker|star)", combined_news):
            sentiment_news += 3

    # 4. Analyze Preview (General Sentiment)
    # Map 'situational_factors' to preview logic
    texts_prev = categorized_texts.get("preview", []) + categorized_texts.get("situational_factors", [])
    if texts_prev:
        combined_prev = " ".join(texts_prev).lower()
        total_text_len += len(texts_prev)
        all_combined_text += combined_prev
        
        # Simple regex for general sentiment
        if re.search(rf"{home}\s+(to win|clean sheet|dominat)", combined_prev): sentiment_preview += 2
        if re.search(rf"{away}\s+(to win|clean sheet|dominat)", combined_prev): sentiment_preview -= 2

    # Draw Signals (Global)
    draw_signals = 0
    if re.search(r"(draw|stalemate|tight match|share the spoils)", all_combined_text):
        draw_signals += 1
    
    # BTTS (Global)
    btts_score = 0
    if re.search(r"(both teams to score|btts)", all_combined_text):
        btts_score += 3
    if "2-1" in all_combined_text or "1-2" in all_combined_text or "1-1" in all_combined_text:
        btts_score += 1

    # DC (Global)
    dc = {"1X": 0, "X2": 0, "12": 0}
    if "home or draw" in all_combined_text: dc["1X"] += 1
    if "away or draw" in all_combined_text: dc["X2"] += 1

    # Calculate Aggregate Net Score (for Poisson / compatibility)
    # Same logic as Model to ensure consistency
    net_score = 0
    net_score += sentiment_prediction * 2.0
    net_score += sentiment_form * 1.5
    net_score += sentiment_news * 1.0
    net_score += sentiment_preview * 0.8

    # NEW: Extract Form Scores and Goals Stats
    home_form_score = extract_form_score(all_combined_text, home_team)
    away_form_score = extract_form_score(all_combined_text, away_team)
    
    home_goals = extract_goals_stats(all_combined_text, home_team)
    away_goals = extract_goals_stats(all_combined_text, away_team)
    
    # Calculate form differential (positive = home advantage)
    form_differential = home_form_score - away_form_score

    return {
        "sentiments": {
            "prediction": sentiment_prediction,
            "form": sentiment_form,
            "news": sentiment_news,
            "preview": sentiment_preview
        },
        "net_score": net_score,
        "draw_signals": draw_signals,
        "btts_score": btts_score,
        "dc_counts": dc,
        "valid_scores": valid_scores,
        "text_volume": total_text_len,
        # NEW: Real Statistics
        "form_differential": form_differential,
        "home_form_score": home_form_score,
        "away_form_score": away_form_score,
        "home_goals_for": home_goals['goals_for'],
        "home_goals_against": home_goals['goals_against'],
        "away_goals_for": away_goals['goals_for'],
        "away_goals_against": away_goals['goals_against']
    }
