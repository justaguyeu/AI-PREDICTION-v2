from engine.search import build_queries
from engine.scrape import scrape_articles
from engine.nlp import analyze_text
from engine.model import predict_match
from engine.poisson import best_correct_scores
import time

matches = [
    ("Manchester United", "Bournemouth", "4-4"),
    ("Crystal Palace", "Manchester City", "0-3"),
    ("Nottingham Forest", "Tottenham Hotspur", "3-0"),
    ("Sunderland", "Newcastle United", "1-0"),
    ("West Ham United", "Aston Villa", "2-3"),
    ("Brentford", "Leeds United", "1-1"),
    ("Roma", "Como", "1-0")
]

print(f"{'MATCH':<40} | {'RESULT':<10} | {'PREDICTION':<10} | {'CONFIDENCE':<10}")
print("-" * 80)

for home, away, result in matches:
    # 1. Build Queries
    queries_dict = build_queries(home, away)
    # 2. Scrape
    texts_dict = {}
    for cat, q_list in queries_dict.items():
         texts_dict[cat] = scrape_articles(q_list)
         
    # 3. Analyze
    analysis = analyze_text(texts_dict, home, away)
    
    pred_str = "N/A"
    conf_str = "0%"
    
    if analysis["text_volume"] > 0:
        # 4. Predict
        pred = predict_match(analysis)
        pred_str = pred['1x2']['prediction']
        conf_str = pred['1x2']['confidence']
    
    print(f"{home} vs {away:<20} | {result:<10} | {pred_str:<10} | {conf_str:<10}")
    time.sleep(1)
