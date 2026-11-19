"""
engine/model.py
===============
Prediction pipeline:

  1. Map the BetPawa league to football-data leagues and fit a Dixon-Coles
     model on real results from that country (cached per process).
  2. Remove the margin from BetPawa's 1X2 odds -> market probabilities.
  3. Blend model + market (weight tuned by backtest.py), solve for the goal
     rates that reproduce the blended 1X2, and derive all 14 markets from
     that one score matrix (so markets cannot contradict each other).
  4. Attach calibrated hit rates, three separate confidence measures, the
     risks that could make the prediction wrong, expected value against the
     supplied odds, and descriptive match context (form, head-to-head).

Data sources, best to worst:
  model+market – team ratings from real results AND bookmaker odds
  market       – odds only (league not covered, or a team has too few matches)
  model        – ratings only (no valid odds supplied)
  none         – nothing known; no prediction should be acted on
"""
import datetime
import os
import time

import numpy as np
import pandas as pd

from engine import calibration
from engine import dixon_coles as dc
from engine.analysis import match_context
from engine.data import LEAGUES, country_codes, load_country, match_team, resolve_league
from engine.market import blend, implied_probs, outcome_probs, overround, rates_from_1x2
from engine.poisson import all_markets
from engine.results import recent_league_results, recent_other_matches

MODEL_VERSION = "dc-v7"     # bump whenever the probabilities can change for the same inputs
MODEL_TTL = 6 * 3600
DEFAULT_RHO = -0.05
MIN_TEAM_MATCHES = 5        # a rating from fewer matches (e.g. a promoted side's first game) is not used
SOLID_TEAM_MATCHES = 10
_MODELS: dict[str, tuple[float, dc.DCModel | None, pd.DataFrame]] = {}

# Prediction strength, on the calibrated 1X2 hit rate (engine/calibration.json).
HIGH_PROB, MEDIUM_PROB = 0.60, 0.50
# Value flags: EV = model probability x decimal odds - 1 (the results model's own probability).
# OFF by default: in review.py over 14,667 matches, backing every outcome where this model saw an EV
# of +5% or more lost 13-22% (EV >= +10%: -15% to -21%). Set env VALUE_EV_THRESHOLD (e.g. 0.10) to
# switch flags on anyway; the dashboard always shows the EV numbers and this record.
_thr = os.environ.get("VALUE_EV_THRESHOLD", "").strip()
VALUE_EV_THRESHOLD = float(_thr) if _thr else None
VALUE_HISTORY = ("Historically (review.py, 14,667 matches with real pre-match odds) backing outcomes where "
                 "this model's EV was +5% or more lost 13-22%: the bookmaker's price has been more accurate "
                 "than the model. Flags are therefore off unless VALUE_EV_THRESHOLD is set, and even then a "
                 "flag means 'worth a closer look', never expected profit.")

# markets key -> name used by review.py / calibration.json
CAL_NAMES = {
    "1x2_ft": "1X2", "double_chance": "Double chance", "ou_ft": "O/U 2.5", "btts": "BTTS",
    "ou_home": "Home O/U 1.5", "ou_away": "Away O/U 1.5", "handicap": "Handicap -1",
    "1x2_h1": "1X2 1st half", "ou_h1": "O/U 1st half", "1x2_h2": "1X2 2nd half",
    "ou_h2": "O/U 2nd half", "ht_ft": "HT/FT",
}
# Draw risk from the final draw probability. Measured on 14,667 matches (review.py, 2025/26 to
# Oct 2026): LOW ended level ~24% of the time, MEDIUM ~29%, HIGH 30-34% (normal rate ~25%).
# A draw is almost never the single most likely result, so the 1X2 pick stays home/away;
# picking DRAW above a threshold was tested and lost accuracy on unseen matches.
DRAW_RISK = [
    (0.30, "HIGH", "about 1 in 3 matches like this end in a draw (normal rate 1 in 4)"),
    (0.27, "MEDIUM", "about 29% of matches like this end in a draw (normal rate 25%)"),
    (0.00, "LOW", "a draw is less likely than usual (about 24%)"),
]

CONFIDENCE_CRITERIA = {
    "prediction_strength": "HIGH if the 1X2 pick's calibrated hit rate is >= 60%, MEDIUM 50-60%, LOW below "
                           "50% (or no data).",
    "data_quality": "HIGH: results ratings for both teams (>= 10 matches in 12 months) AND valid odds. "
                    "MEDIUM: odds only, or ratings with 5-9 matches, or ratings only with >= 10 matches. "
                    "LOW: ratings only with 5-9 matches. INSUFFICIENT: neither ratings nor odds.",
    "model_confidence": "HIGH: data quality HIGH and model and bookmaker agree within 8 points on every "
                        "1X2 outcome. LOW: they differ by more than 15 points, or data quality LOW. "
                        "MEDIUM otherwise. INSUFFICIENT without data.",
}


def draw_risk(p_draw: float) -> dict:
    level, note = next((lvl, n) for t, lvl, n in DRAW_RISK if p_draw >= t)
    return {"level": level, "prob": round(p_draw * 100, 1), "note": note}


# Markets considered for the per-match "safest pick" (main-line markets every bookmaker offers)
SAFE_MARKETS = ["1X2", "Double chance", "O/U 1.5", "O/U 2.5", "O/U 3.5", "BTTS", "Home O/U 1.5", "Away O/U 1.5"]


def _add_hit_rates(markets: dict) -> dict:
    """Attach the calibrated hit rate to every pick; return the most likely winning pick."""
    candidates = []
    for key, name in CAL_NAMES.items():
        m = markets[key]
        p = calibration.hit_rate(name, float(m["confidence"].rstrip("%")) / 100)
        m["hit_rate"] = f"{p * 100:.1f}%"
        candidates.append((name, m["prediction"], p))
    for t in markets["ou_ft"]["all_thresholds"]:
        name = f"O/U {float(t['label'][1:])}"
        if name in ("O/U 1.5", "O/U 3.5"):
            p = calibration.hit_rate(name, t["confidence"] / 100)
            t["hit_rate"] = round(p * 100, 1)
            candidates.append((name, f"{t['pick']} {float(t['label'][1:])}", p))
    name, pick, p = max((c for c in candidates if c[0] in SAFE_MARKETS), key=lambda c: c[2])
    return {"market": name, "pick": pick, "hit_rate": round(p * 100, 1), "fair_odds": round(1 / p, 2)}


# ── Model cache ──────────────────────────────────────────────────────────────

def get_model(code: str) -> dc.DCModel | None:
    """Dixon-Coles model for every division of `code`'s country."""
    key = country_codes(code)[0]
    cached = _MODELS.get(key)
    if cached and time.time() - cached[0] < MODEL_TTL:
        return cached[1]
    df = load_country(key)
    if not df.empty:
        try:
            fresh = recent_league_results(df, country_codes(key))
        except Exception as e:          # ESPN is a bonus; never block a prediction on it
            print(f"  [Model] ESPN results unavailable: {e}")
            fresh = pd.DataFrame()
        if not fresh.empty:
            df = pd.concat([df, fresh], ignore_index=True)
    model = dc.fit(df, league=key) if not df.empty else None
    _MODELS[key] = (time.time(), model, df)
    return model


_OTHER: dict[str, tuple[float, pd.DataFrame]] = {}


def get_other_matches(model: dc.DCModel | None) -> pd.DataFrame | None:
    """Recent cup/continental matches of this country's teams (for complete rest days)."""
    if model is None:
        return None
    cached = _OTHER.get(model.league)
    if cached and time.time() - cached[0] < MODEL_TTL:
        return cached[1]
    try:
        other = recent_other_matches(LEAGUES[model.league][1], model.teams)
    except Exception as e:                      # descriptive only; never block a prediction
        print(f"  [Model] cup/continental matches unavailable: {e}")
        other = None
    _OTHER[model.league] = (time.time(), other)
    return other


def get_history(model: dc.DCModel | None) -> pd.DataFrame | None:
    cached = _MODELS.get(model.league) if model else None
    return cached[2] if cached and cached[1] is model else None


def locate(home: str, away: str, league: str | None = None):
    """
    Find a fitted model containing both teams.
    Returns (model, home_name, away_name, league_matched_exactly).
    """
    codes, exact = resolve_league(league)
    if not codes and not league:
        codes = list(LEAGUES)          # unknown league: search every country
    tried = set()
    for code in codes:
        key = country_codes(code)[0]
        if key in tried:
            continue
        tried.add(key)
        model = get_model(code)
        if model is None:
            continue
        h, _ = match_team(home, model.teams)
        a, _ = match_team(away, model.teams)
        if h and a and h != a and model.is_current(h) and model.is_current(a):
            return model, h, a, exact
    return None, None, None, exact


# ── Assessment ───────────────────────────────────────────────────────────────

def _data_quality(src, model, h_name, a_name) -> dict:
    reasons = []
    if src == "none":
        return {"level": "INSUFFICIENT", "reasons": ["No results data for these teams and no valid odds."]}
    if src in ("model+market", "model"):
        counts = (model.recent[h_name], model.recent[a_name])
        reasons.append(f"Ratings from {counts[0]} and {counts[1]} matches in the last 12 months.")
        solid = min(counts) >= SOLID_TEAM_MATCHES
    if src == "model+market":
        reasons.append("Valid bookmaker odds supplied.")
        level = "HIGH" if solid else "MEDIUM"
    elif src == "market":
        reasons.append("Odds only: no usable results ratings for at least one team.")
        level = "MEDIUM"
    else:
        reasons.append("No valid odds supplied to cross-check the ratings.")
        level = "MEDIUM" if solid else "LOW"
    reasons.append("Injuries, suspensions and line-ups are not included (no data source).")
    return {"level": level, "reasons": reasons}


def _agreement(p_model, p_market) -> float | None:
    if p_model is None or p_market is None:
        return None
    return float(np.abs(np.asarray(p_model) - np.asarray(p_market)).max())


def _model_confidence(quality: str, gap: float | None) -> dict:
    if quality == "INSUFFICIENT":
        return {"level": "INSUFFICIENT", "reasons": ["Nothing to base a prediction on."]}
    reasons = []
    if gap is not None:
        reasons.append(f"Model and bookmaker differ by up to {gap * 100:.0f} points on the 1X2.")
    if quality == "LOW" or (gap is not None and gap > 0.15):
        level = "LOW"
    elif quality == "HIGH" and gap is not None and gap <= 0.08:
        level = "HIGH"
    else:
        level = "MEDIUM"
    reasons.append(f"Data quality {quality}.")
    return {"level": level, "reasons": reasons}


def _value(odds, p, p_model, src, quality, confidence) -> dict | None:
    if odds is None or implied_probs(odds) is None:
        return None
    fair = implied_probs(odds)
    eligible = (VALUE_EV_THRESHOLD is not None and p_model is not None
                and quality in ("HIGH", "MEDIUM") and confidence != "LOW")
    rows = []
    for i, name in enumerate(("HOME WIN", "DRAW", "AWAY WIN")):
        o = float(odds[i])
        ev = float(p[i]) * o - 1
        ev_model = float(p_model[i]) * o - 1 if p_model is not None else None
        rows.append({"outcome": name, "odds": o, "implied": round(100 / o, 1), "fair": round(fair[i] * 100, 1),
                     "probability": round(float(p[i]) * 100, 1), "ev": round(ev * 100, 1),
                     "model_probability": round(float(p_model[i]) * 100, 1) if p_model is not None else None,
                     "ev_model": round(ev_model * 100, 1) if ev_model is not None else None,
                     "flag": bool(eligible and ev_model >= VALUE_EV_THRESHOLD)})
    return {"threshold": round(VALUE_EV_THRESHOLD * 100, 1) if VALUE_EV_THRESHOLD is not None else None,
            "overround": round((overround(odds) - 1) * 100, 1), "outcomes": rows, "eligible": eligible,
            "assumptions": "EV per 1 unit staked = probability x decimal odds - 1, assuming the odds shown are "
                           "still available. 'Final' EV uses the published probability (the odds without "
                           "margin), so it is negative by about the margin; 'model' EV uses the results "
                           "model's own probability.",
            "history": VALUE_HISTORY}


def _risks(src, p_cal_top, pick, draw, gap, p_model, p_market, model, h_name, a_name, home, away,
           competition_note, context, rejected) -> list[str]:
    risks = []
    if src == "none":
        return ["No results data and no odds: this is a league-average placeholder, not a prediction."]
    risks.append(f"Even at its stated hit rate the pick '{pick}' fails about {(1 - p_cal_top) * 100:.0f}% of "
                 f"the time.")
    if draw["level"] != "LOW":
        risks.append(f"Draw risk {draw['level']} ({draw['prob']:.0f}%): {draw['note']}.")
    if gap is not None and gap > 0.10:
        names = ["home win", "draw", "away win"]
        i = int(np.argmax(np.abs(np.asarray(p_model) - np.asarray(p_market))))
        risks.append(f"Model and bookmaker disagree on the {names[i]} ({p_model[i]:.0%} vs {p_market[i]:.0%}); "
                     f"one of them is missing something.")
    for msg in rejected:
        risks.append(msg)
    if model and h_name:
        for team, name in ((home, h_name), (away, a_name)):
            if model.recent.get(name, 0) < SOLID_TEAM_MATCHES:
                risks.append(f"Only {model.recent.get(name, 0)} recent matches for {team}: its rating is uncertain.")
    if src == "market":
        risks.append("Based on the odds alone: no independent check from results data.")
    if src == "model":
        risks.append("No valid odds: the bookmaker's information (team news, form) is not reflected.")
    if competition_note:
        risks.append(competition_note)
    if context:
        rd = context["rest_days"]
        lm = context.get("last_match") or {}
        for team, d, side in ((home, rd["home"], "home"), (away, rd["away"], "away")):
            if d is not None and d <= 3:
                comp = (lm.get(side) or {}).get("competition", "league")
                what = "a league match" if comp == "league" else f"a {comp} match"
                risks.append(f"{team} played {what} {d} days ago: possible fatigue or rotation.")
        through = context.get("data_through")
        if through and (pd.Timestamp.today() - pd.Timestamp(through)).days > 21:
            risks.append(f"Latest result in the data is from {through}: ratings may be out of date.")
    risks.append("Injuries, suspensions and line-ups are not included: check official team news before kickoff.")
    return risks


def _factors(src, home, away, p_model, p_market, lam, mu, model, h_name, a_name, context) -> list[str]:
    f = []
    if src == "model+market":
        f.append(f"💹 Probabilities from BetPawa odds with the margin removed; team ratings from "
                 f"{model.recent[h_name] + model.recent[a_name]} recent real matches are used as a cross-check "
                 f"(in testing, the odds alone were more accurate than any mix with the ratings).")
    elif src == "market":
        f.append("💹 Probabilities come from BetPawa odds with the bookmaker margin removed.")
    elif src == "model":
        f.append("📊 Ratings from real results; no odds were supplied to cross-check.")
    else:
        f.append("⚠️ No results data and no odds for these teams — this is a league-average guess. "
                 "Do not bet on it.")

    if model and h_name:
        hs, hc = model.team_goals(h_name)
        as_, ac = model.team_goals(a_name)
        f.append(f"⚽ {home}: {hs:.2f} scored / {hc:.2f} conceded per game vs an average side. "
                 f"{away}: {as_:.2f} / {ac:.2f}.")
    if p_model is not None and p_market is not None:
        if _agreement(p_model, p_market) <= 0.10:
            f.append("✅ The ratings model agrees closely with the bookmaker.")
        else:
            f.append("🔍 The ratings model disagrees with the bookmaker (see risks); the bookmaker has been "
                     "more accurate in testing, so the published numbers follow the odds.")
    if context:
        hf, af = context["home_form"]["last5"], context["away_form"]["last5"]
        if hf and af:
            f.append(f"📈 Last 5: {home} {hf['sequence']} ({hf['ppg']} pts/game), "
                     f"{away} {af['sequence']} ({af['ppg']} pts/game).")
        hh, aa = context["home_at_home"], context["away_away"]
        if hh and aa:
            f.append(f"🏟️ {home} at home: {hh['w']}W {hh['d']}D {hh['l']}L in last {hh['matches']}; "
                     f"{away} away: {aa['w']}W {aa['d']}D {aa['l']}L in last {aa['matches']}.")
        h2h = context["h2h"]
        if h2h["meetings"]:
            f.append(f"🤜 Head-to-head (last {len(h2h['meetings'])} in the data): {home} {h2h['home_wins']}, "
                     f"draws {h2h['draws']}, {away} {h2h['away_wins']} — shown for context, not used in the "
                     f"probabilities.")
        hx = context["home_form"]["last5"]
        ax = context["away_form"]["last5"]
        if hx and ax and "xg_for" in hx and "xg_for" in ax:
            f.append(f"🎯 xG last 5: {home} {hx['xg_for']} for / {hx['xg_against']} against; "
                     f"{away} {ax['xg_for']} / {ax['xg_against']}.")
    f.append(f"🎯 Expected goals this match: {home} {lam:.2f} – {away} {mu:.2f}.")
    return f


# ── Prediction ───────────────────────────────────────────────────────────────

def predict_match(home_team: str, away_team: str, league: str | None = None, odds=None) -> dict:
    """
    home_team, away_team : names as shown on BetPawa
    league               : e.g. "Football / England / Premier League" (optional but recommended)
    odds                 : (home, draw, away) decimal odds (optional but recommended)
    """
    model, h_name, a_name, exact = locate(home_team, away_team, league)
    note = None
    if model and league and not exact:
        note = ("Not a league match covered by the data (cup or other competition): ratings come from league "
                "games, and rotation, extra time or two-leg ties are not modelled.")
    return predict_with_model(model, h_name, a_name, home_team, away_team, league, odds,
                              history=get_history(model), competition_note=note,
                              other_matches=get_other_matches(model))


def predict_with_model(model, h_name, a_name, home_team, away_team, league=None, odds=None,
                       history: pd.DataFrame | None = None, competition_note: str | None = None,
                       other_matches: pd.DataFrame | None = None) -> dict:
    """Core of predict_match with the model supplied (review.py passes one fitted at a past date)."""
    rejected = []
    p_market = implied_probs(odds)
    if odds is not None and p_market is None:
        rejected.append(f"Odds {list(odds)} were rejected as invalid (their margin is impossible for a real "
                        f"1X2 market), so they are not used.")
    if model and h_name and min(model.recent.get(h_name, 0), model.recent.get(a_name, 0)) < MIN_TEAM_MATCHES:
        few = home_team if model.recent.get(h_name, 0) < MIN_TEAM_MATCHES else away_team
        rejected.append(f"{few} has fewer than {MIN_TEAM_MATCHES} matches in the data (e.g. newly promoted), so "
                        f"the team ratings are not used.")
        model, h_name, a_name = None, None, None
    rho = model.rho if model else DEFAULT_RHO

    p_model = None
    if model:
        lam_m, mu_m = model.rates(h_name, a_name)
        p_model = outcome_probs(dc.score_matrix(lam_m, mu_m, rho))

    if p_model is not None and p_market is not None:
        src = "model+market"
        p = blend(p_model, p_market)
        lam, mu = rates_from_1x2(p, rho, start=(lam_m, mu_m))
    elif p_market is not None:
        src = "market"
        p = p_market
        lam, mu = rates_from_1x2(p, rho)
    elif p_model is not None:
        src = "model"
        p = p_model
        lam, mu = lam_m, mu_m
    else:
        src = "none"
        lam, mu = 1.45, 1.15
        p = outcome_probs(dc.score_matrix(lam, mu, rho))

    markets, scores, meta = all_markets(lam, mu, rho, home_team, away_team)
    p = outcome_probs(dc.score_matrix(lam, mu, rho))          # the matrix every market is read from
    safest = _add_hit_rates(markets) if src != "none" else None
    draw = draw_risk(float(p[1]))
    context = None
    if history is not None and h_name:
        try:
            context = match_context(history, h_name, a_name, model, other=other_matches)
        except Exception as e:                                 # context is descriptive; never block on it
            print(f"  [Model] match context unavailable: {e}")

    pick = markets["1x2_ft"]["prediction"]
    p_cal_top = float(markets["1x2_ft"]["hit_rate"].rstrip("%")) / 100 if src != "none" else float(np.max(p))
    quality = _data_quality(src, model, h_name, a_name)
    gap = _agreement(p_model, p_market)
    confidence = _model_confidence(quality["level"], gap)
    if src == "none":
        strength = "LOW"
    elif p_cal_top >= HIGH_PROB:
        strength = "HIGH"
    elif p_cal_top >= MEDIUM_PROB:
        strength = "MEDIUM"
    else:
        strength = "LOW"

    factors = _factors(src, home_team, away_team, p_model, p_market, lam, mu, model, h_name, a_name, context)
    risks = _risks(src, p_cal_top, pick, draw, gap, p_model, p_market, model, h_name, a_name, home_team,
                   away_team, competition_note, context, rejected)
    value = _value(odds, p, p_model, src, quality["level"], confidence["level"])

    team_stats = {"home_attack": None, "home_defense": None, "away_attack": None, "away_defense": None,
                  "data_source": src}                       # only real ratings, never stand-ins
    if model and h_name:
        hs, hc = model.team_goals(h_name)
        as_, ac = model.team_goals(a_name)
        team_stats.update(home_attack=round(hs, 2), home_defense=round(hc, 2),
                          away_attack=round(as_, 2), away_defense=round(ac, 2))

    def pct(x):
        return None if x is None else {k: round(float(v) * 100, 1) for k, v in zip("1X2", x)}

    ou = {t["label"][1:]: t["over"] for t in markets["ou_ft"]["all_thresholds"]}
    sources = []
    if history is not None:
        sources.append({"name": "football-data.co.uk results (+ ESPN for the latest round)",
                        "data_through": context["data_through"] if context else None})
    elif model is not None:
        sources.append({"name": "football-data.co.uk results", "data_through": None})
    if p_market is not None:
        sources.append({"name": "BetPawa 1X2 odds", "data_through": None})

    return {
        "status": "success",
        "model_version": MODEL_VERSION,
        "created_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "home": home_team,
        "away": away_team,
        "league": league,
        "odds": list(odds) if odds else None,
        "overall_confidence": strength,
        "probabilities": {
            "home": round(float(p[0]) * 100, 1), "draw": round(float(p[1]) * 100, 1),
            "away": round(float(p[2]) * 100, 1), "most_likely": pick,
            "most_likely_hit_rate": round(p_cal_top * 100, 1),
            "high_confidence": strength == "HIGH" and confidence["level"] in ("HIGH", "MEDIUM"),
        },
        "expected_goals": {"home": round(lam, 2), "away": round(mu, 2)},
        "goals": {"btts_yes": markets["btts"]["options"]["YES"], "over_1_5": ou.get("1.5"),
                  "over_2_5": ou.get("2.5"), "over_3_5": ou.get("3.5")},
        "assessment": {
            "prediction_strength": {"level": strength},
            "model_confidence": confidence,
            "data_quality": quality,
            "criteria": CONFIDENCE_CRITERIA,
        },
        "markets": markets,
        "correct_scores": scores,
        "analysis_meta": {**meta, "data_source": src, "stats_driven": model is not None,
                          "matched_teams": [h_name, a_name] if h_name else None,
                          "model_1x2": pct(p_model), "market_1x2": pct(p_market)},
        "safest_pick": safest,
        "draw_risk": draw,
        "best_bet": ({"market": safest["market"], "pick": safest["pick"], "confidence": f"{safest['hit_rate']:.1f}%"}
                     if safest else {"market": "", "pick": "", "confidence": ""}),
        "value": value,
        "factors": factors,
        "risks": risks,
        "context": context,
        "sources": sources,
        "reasoning": " ".join(factors),
        "team_stats": team_stats,
    }
