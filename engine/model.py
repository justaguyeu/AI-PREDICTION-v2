from engine.poisson import all_markets

def predict_match(analysis, home_team="", away_team=""):
    """
    Takes NLP sentiment analysis and derives all 14 prediction markets.
    """
    # 1. Provide a quick summary logic for 'Overall Confidence'
    # Based on sentiment spread and data volume
    net_score = abs(analysis.get("net_score", 0))
    vol = analysis.get("text_volume", 0)
    
    if vol < 3 or net_score < 2:
        confidence = "LOW"
    elif net_score >= 5 and vol >= 6:
        confidence = "HIGH"
    else:
        confidence = "MEDIUM"
        
    # 2. Derive all 14 markets using Poisson engine
    markets, correct_scores, metadata = all_markets(analysis, home_team, away_team)
    
    # 3. Construct Final Envelope (Backwards-compatible wrapper plus new fields)
    return {
        "status": "success",
        "home": home_team,
        "away": away_team,
        "overall_confidence": confidence,
        "markets": markets,
        "correct_scores": correct_scores,
        "analysis_meta": metadata,
        
        # Legacy fields for storage backwards compatibility if needed
        "score": net_score,
        "draw_signals": analysis.get("draw_signals", 0)
    }
