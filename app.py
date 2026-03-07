from flask import Flask, jsonify, request, render_template
import time
from engine.betpawa import scrape_matches
from engine.model import predict_match
from engine.search import build_queries
from engine.scrape import scrape_articles
from engine.nlp import analyze_text
from engine.storage import get_prediction, save_prediction

app = Flask(__name__)

# Simple in-memory cache for today's matches
MATCHES_CACHE = {
    "data": [],
    "last_updated": 0
}
CACHE_TTL = 0  # Disabled for immediate verification of scraper fix

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/matches")
def api_matches():
    now = time.time()
    if MATCHES_CACHE["data"] and (now - MATCHES_CACHE["last_updated"]) < CACHE_TTL:
        return jsonify({"matches": MATCHES_CACHE["data"]})
        
    try:
        results = scrape_matches()
        if results:
            dicts = [{"home": h, "away": a} for (h, a) in results]
            MATCHES_CACHE["data"] = dicts
            MATCHES_CACHE["last_updated"] = now
            return jsonify({"matches": dicts})
        else:
            return jsonify({"error": "No matches found on BetPawa today"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/predict", methods=["POST"])
def api_predict():
    data = request.json
    home = data.get("home")
    away = data.get("away")
    
    if not home or not away:
        return jsonify({"error": "Missing home or away team"}), 400
        
    # Check disk cache
    cached = get_prediction(home, away)
    if cached and cached.get("status") == "success":
        return jsonify(cached)
        
    # Analyze
    try:
        queries_dict = build_queries(home, away)
        all_texts = {}
        for cat, q_list in queries_dict.items():
            all_texts[cat] = scrape_articles(q_list)
            
        analysis = analyze_text(all_texts, home, away)
        
        if analysis.get("text_volume", 0) < 1:
            return jsonify({"status": "insufficient_data"}), 200
            
        prediction = predict_match(analysis, home, away)
        save_prediction(home, away, prediction)
        
        return jsonify(prediction)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
