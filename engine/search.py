# def build_queries(home, away):
#     home = home.strip()
#     away = away.strip()

#     return [
#         f"{home} vs {away} match preview",
#         f"{home} vs {away} prediction",
#         f"{home} vs {away} head to head"
#     ]
def build_queries(home, away):
    home = home.strip()
    away = away.strip()

    return {
        "tactical_edge": [
            f"{home} vs {away} predicted lineups confirmed", # Crucial for player-prop betting
            f"{home} vs {away} tactical analysis", # Look for "low block" or "high press" shifts
            f"{home} vs {away} expected goals xG stats", # Underlying performance vs surface results
            f"{home} goals scored conceded this season",  # NEW: goals stats
            f"{away} goals scored conceded this season"   # NEW: goals stats
        ],
        "market_sentiment": [
            f"{home} vs {away} odds movement analysis", # Spotting "smart money" or "steam moves"
            f"{home} vs {away} betting public percentage" # Fading the public strategies
        ],
        "situational_factors": [
            f"{home} vs {away} referee stats yellow cards", # For card/booking markets
            f"{home} vs {away} weather report pitch conditions", # Affects Total Goals (Over/Under)
            f"{home} vs {away} travel distance fixture congestion" # Fatigue factors
        ],
        "injury_deep_dive": [
            f"{home} injury report {away} missing players list", 
            f"is {home} star player starting vs {away}" # High-impact player check
        ],
        "h2h_context": [
            f"{home} vs {away} head to head home away record",
            f"{home} vs {away} last 5 matches goal scorers",
            f"{home} recent form table W D L",  # NEW: target form data
            f"{away} recent form table W D L",  # NEW: target form data
            f"{home} vs {away} last 10 meetings results"  # NEW: better H2H
        ]
    }
