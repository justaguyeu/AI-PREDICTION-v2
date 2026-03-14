from flask import Flask, jsonify, request, render_template
import time
from engine.betpawa import scrape_matches
from engine.model import predict_match
from engine.search import build_queries
from engine.scrape import scrape_articles
from engine.nlp import analyze_text
from engine.storage import get_prediction, save_prediction, load_all_predictions

app = Flask(__name__)

# In-memory cache
MATCHES_CACHE = {"data": [], "last_updated": 0}
CACHE_TTL = 300  # 5 minutes

@app.route("/")
def index():
    return render_template("index.html")

# ── /api/matches ──────────────────────────────────────────────────────────────
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

# ── /api/predict ──────────────────────────────────────────────────────────────
@app.route("/api/predict", methods=["POST"])
def api_predict():
    data = request.json
    home = data.get("home", "").strip()
    away = data.get("away", "").strip()
    if not home or not away:
        return jsonify({"error": "Missing home or away team"}), 400

    # Check cache
    cached = get_prediction(home, away)
    if cached and cached.get("status") == "success":
        return jsonify(cached)

    try:
        queries_dict = build_queries(home, away)
        all_texts = {}
        for cat, q_list in queries_dict.items():
            all_texts[cat] = scrape_articles(q_list)

        analysis = analyze_text(all_texts, home, away)

        # We no longer gate on text_volume — real stats fill the gap
        prediction = predict_match(analysis, home, away)
        save_prediction(home, away, prediction)
        return jsonify(prediction)

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── /api/best-bets ────────────────────────────────────────────────────────────
@app.route("/api/best-bets")
def api_best_bets():
    """
    Returns the top best-bet picks from today's cached predictions.
    Only includes predictions that have already been computed (cached).
    """
    try:
        all_preds = load_all_predictions()
        bets = []
        for key, pred in all_preds.items():
            if pred.get("status") != "success":
                continue
            bb = pred.get("best_bet", {})
            if not bb or not bb.get("pick"):
                continue
            try:
                conf = float(bb.get("confidence", "0%").replace("%", ""))
            except Exception:
                conf = 0.0
            bets.append({
                "home":       pred.get("home", ""),
                "away":       pred.get("away", ""),
                "market":     bb.get("market", ""),
                "pick":       bb.get("pick", ""),
                "confidence": bb.get("confidence", ""),
                "conf_float": conf,
                "overall_confidence": pred.get("overall_confidence", "LOW"),
                "data_source": (pred.get("team_stats") or {}).get("data_source", "unknown"),
            })

        # Sort by confidence descending, return top 5
        bets.sort(key=lambda x: x["conf_float"], reverse=True)
        top = [{k: v for k, v in b.items() if k != "conf_float"} for b in bets[:5]]
        return jsonify({"best_bets": top})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
