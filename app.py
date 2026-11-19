from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
import datetime
import time
from engine import calibration
from engine.betpawa import scrape_matches
from engine.model import MODEL_VERSION, predict_match
from engine.storage import get_prediction, save_prediction, load_all_predictions

app = Flask(__name__)
CORS(app)  # Allow React dev server (localhost:5173) to call this API

# In-memory cache
MATCHES_CACHE = {"data": [], "last_updated": 0}
CACHE_TTL = 300  # 5 minutes


def _iso(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).isoformat(timespec="seconds")


# ── /api/health ───────────────────────────────────────────────────────────────
@app.route("/api/health")
def api_health():
    try:
        cal = calibration.meta()
    except Exception:
        cal = {}
    return jsonify({"status": "ok", "model_version": MODEL_VERSION, "calibration": cal})

# ── / ─────────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    try:
        return render_template("index.html")
    except Exception:
        return jsonify({"status": "running", "endpoints": ["/api/matches", "/api/predict", "/api/best-bets"]}), 200

# ── /api/matches ──────────────────────────────────────────────────────────────
@app.route("/api/matches")
def api_matches():
    now = time.time()
    if MATCHES_CACHE["data"] and (now - MATCHES_CACHE["last_updated"]) < CACHE_TTL:
        return jsonify({"matches": MATCHES_CACHE["data"], "source": "BetPawa TZ",
                        "scraped_at": _iso(MATCHES_CACHE["last_updated"])})
    try:
        results = scrape_matches()
        if results:
            MATCHES_CACHE["data"] = results
            MATCHES_CACHE["last_updated"] = now
            return jsonify({"matches": results, "source": "BetPawa TZ", "scraped_at": _iso(now)})
        else:
            return jsonify({"error": "No matches found on BetPawa today"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── /api/predict ──────────────────────────────────────────────────────────────
def _validate(data: dict):
    """Returns (home, away, league, odds, kickoff) or raises ValueError with a message for the client."""
    home = str(data.get("home") or "").strip()
    away = str(data.get("away") or "").strip()
    if not home or not away:
        raise ValueError("Missing home or away team")
    if len(home) > 80 or len(away) > 80:
        raise ValueError("Team name too long")
    league = data.get("league")
    if league is not None and (not isinstance(league, str) or len(league) > 150):
        raise ValueError("league must be a short string")
    odds = data.get("odds")
    if odds is not None:
        if not isinstance(odds, (list, tuple)) or len(odds) != 3:
            raise ValueError("odds must be a list of three decimal odds [home, draw, away]")
        try:
            odds = [float(x) for x in odds]
        except (TypeError, ValueError):
            raise ValueError("odds must be numbers")
        if any(not (1.0 < x < 1000) for x in odds):
            raise ValueError("each decimal odd must be between 1 and 1000")
    kickoff = data.get("kickoff")
    kickoff = str(kickoff)[:40] if kickoff else None
    return home, away, league, odds, kickoff


@app.route("/api/predict", methods=["POST"])
def api_predict():
    try:
        home, away, league, odds, kickoff = _validate(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Check cache
    cached = get_prediction(home, away)
    if cached:
        return jsonify(cached)

    try:
        prediction = predict_match(home, away, league=league, odds=odds)
        prediction["kickoff"] = kickoff
        return jsonify(save_prediction(home, away, prediction))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── /api/best-bets ────────────────────────────────────────────────────────────
@app.route("/api/best-bets")
def api_best_bets():
    """
    Top "safest picks" among today's stored predictions from the current engine.
    Matches without data (league-average placeholders) are never listed.
    """
    try:
        all_preds = load_all_predictions()
        bets = []
        for key, pred in all_preds.items():
            if pred.get("status") != "success" or pred.get("engine") != MODEL_VERSION:
                continue
            sp = pred.get("safest_pick")
            if not sp or (pred.get("analysis_meta") or {}).get("data_source") == "none":
                continue
            bets.append({
                "home":               pred.get("home", ""),
                "away":               pred.get("away", ""),
                "market":             sp["market"],
                "pick":               sp["pick"],
                "confidence":         f"{sp['hit_rate']:.1f}%",
                "fair_odds":          sp["fair_odds"],
                "conf_float":         sp["hit_rate"],
                "overall_confidence": pred.get("overall_confidence", "LOW"),
                "data_quality":       ((pred.get("assessment") or {}).get("data_quality") or {}).get("level"),
                "data_source":        (pred.get("analysis_meta") or {}).get("data_source", "unknown"),
            })

        # Sort by historical hit rate, return top 5
        bets.sort(key=lambda x: x["conf_float"], reverse=True)
        top = [{k: v for k, v in b.items() if k != "conf_float"} for b in bets[:5]]
        return jsonify({"best_bets": top})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, port=5000)
