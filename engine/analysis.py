"""
engine/analysis.py
==================
Descriptive match context computed from the downloaded results (football-data.co.uk,
plus recent ESPN results): recent form, venue form, head-to-head, rest days and,
where published, xG and shots on target.

These numbers are shown to explain a prediction. They are NOT fed into the
probabilities: the Dixon-Coles ratings already weight every past result by recency
and opponent strength, so adding form or head-to-head again would double-count
the same information.

Only league matches in the covered divisions are included (no cups, no European
games) — the output says so via `scope`.
"""
import numpy as np
import pandas as pd

SCOPE = "league matches in the results database (cups and European games not included)"


def _team_rows(df: pd.DataFrame, team: str, before: pd.Timestamp, venue: str | None = None) -> pd.DataFrame:
    played = df[df["hg"].notna() & (df["date"] < before)]
    if venue == "home":
        rows = played[played["home"] == team]
    elif venue == "away":
        rows = played[played["away"] == team]
    else:
        rows = played[(played["home"] == team) | (played["away"] == team)]
    return rows.sort_values("date", ascending=False)


def _summarise(rows: pd.DataFrame, team: str, n: int, model=None, baseline: float | None = None) -> dict | None:
    rows = rows.head(n)
    if rows.empty:
        return None
    is_home = (rows["home"] == team).to_numpy()
    gf = np.where(is_home, rows["hg"], rows["ag"]).astype(float)
    ga = np.where(is_home, rows["ag"], rows["hg"]).astype(float)
    res = np.where(gf > ga, "W", np.where(gf == ga, "D", "L"))
    out = {
        "matches": int(len(rows)),
        "w": int((res == "W").sum()), "d": int((res == "D").sum()), "l": int((res == "L").sum()),
        "gf": int(gf.sum()), "ga": int(ga.sum()),
        "ppg": round(float(((res == "W") * 3 + (res == "D")).mean()), 2),
        "gd": int(gf.sum() - ga.sum()),
        "clean_sheets": int((ga == 0).sum()), "failed_to_score": int((gf == 0).sum()),
        "sequence": "".join(res),                     # most recent first
        "from": rows["date"].min().strftime("%Y-%m-%d"), "to": rows["date"].max().strftime("%Y-%m-%d"),
    }
    # xG / shots on target only where every match in the window has them
    for col_h, col_a, key in (("hxg", "axg", "xg"), ("hst", "ast", "sot")):
        if col_h in rows.columns:
            h, a = rows[col_h].to_numpy(dtype=float), rows[col_a].to_numpy(dtype=float)
            if np.isfinite(h).all() and np.isfinite(a).all():
                f = np.where(is_home, h, a)
                g = np.where(is_home, a, h)
                out[f"{key}_for"] = round(float(f.mean()), 2)
                out[f"{key}_against"] = round(float(g.mean()), 2)
    # strength of opponents faced (model rating = attack - defensive weakness), relative to the average
    # team of this team's current league: 0 = typical schedule, positive = tougher opponents
    if model is not None and baseline is not None:
        opps = np.where(is_home, rows["away"], rows["home"])
        strength = [model.attack[o] - model.defence[o] for o in opps if o in model.attack]
        if strength:
            out["opponent_strength"] = round(float(np.mean(strength)) - baseline, 2)
    return out


def league_baseline(df: pd.DataFrame, team: str, before: pd.Timestamp, model) -> float | None:
    """Average rating of the teams in `team`'s most recent league."""
    if model is None:
        return None
    rows = _team_rows(df, team, before)
    if rows.empty or "league" not in rows.columns:
        return None
    lg = rows["league"].iloc[0]
    recent = df[(df["league"] == lg) & (df["date"] < before) & (df["date"] >= before - pd.Timedelta(days=365))]
    teams = set(recent["home"]) | set(recent["away"])
    vals = [model.attack[t] - model.defence[t] for t in teams if t in model.attack]
    return float(np.mean(vals)) if vals else None


def team_form(df: pd.DataFrame, team: str, before: pd.Timestamp, model=None) -> dict:
    rows = _team_rows(df, team, before)
    base = league_baseline(df, team, before, model)
    return {f"last{n}": _summarise(rows, team, n, model, base) for n in (5, 10, 15)}


def venue_form(df: pd.DataFrame, team: str, venue: str, before: pd.Timestamp, n: int = 10, model=None):
    base = league_baseline(df, team, before, model)
    return _summarise(_team_rows(df, team, before, venue), team, n, model, base)


def head_to_head(df: pd.DataFrame, home: str, away: str, before: pd.Timestamp, n: int = 6) -> dict:
    played = df[df["hg"].notna() & (df["date"] < before)]
    m = played[((played["home"] == home) & (played["away"] == away)) |
               ((played["home"] == away) & (played["away"] == home))].sort_values("date", ascending=False).head(n)
    meetings, wins = [], {"home": 0, "draw": 0, "away": 0}     # from THIS fixture's home team's view
    for r in m.itertuples():
        meetings.append({"date": r.date.strftime("%Y-%m-%d"), "home": r.home, "away": r.away,
                         "score": f"{int(r.hg)}-{int(r.ag)}"})
        if r.hg == r.ag:
            wins["draw"] += 1
        else:
            winner = r.home if r.hg > r.ag else r.away
            wins["home" if winner == home else "away"] += 1
    return {"meetings": meetings, "home_wins": wins["home"], "draws": wins["draw"], "away_wins": wins["away"]}


def last_match(df: pd.DataFrame, team: str, before: pd.Timestamp, other: pd.DataFrame | None = None):
    """Most recent match of any competition we know of: league data plus cup/continental games."""
    best = None
    rows = _team_rows(df, team, before)
    if not rows.empty:
        r = rows.iloc[0]
        opp = r["away"] if r["home"] == team else r["home"]
        best = {"date": r["date"], "competition": "league", "opponent": opp}
    if other is not None and not other.empty:
        o = other[(other["team"] == team) & (other["date"] < before)].sort_values("date")
        if not o.empty and (best is None or o["date"].iloc[-1] > best["date"]):
            r = o.iloc[-1]
            best = {"date": r["date"], "competition": r["competition"], "opponent": r["opponent"]}
    return best


def rest_days(df: pd.DataFrame, team: str, before: pd.Timestamp, other: pd.DataFrame | None = None,
              as_of: pd.Timestamp | None = None):
    """Days from the team's last known match to `as_of` (default `before`)."""
    lm = last_match(df, team, before, other)
    return None if lm is None else int(((as_of if as_of is not None else before) - lm["date"]).days)


def match_context(df: pd.DataFrame, home: str, away: str, model=None, before=None, other=None) -> dict:
    """
    Everything above for one fixture. `before` (exclusive) defaults to tomorrow, so results
    finished today are included, and rest days are then counted up to today.
    `other`: cup/continental matches (engine.results.recent_other_matches) for complete rest days.
    """
    if before is None:
        as_of = pd.Timestamp.today().normalize()
        before = as_of + pd.Timedelta(days=1)
    else:
        before = as_of = pd.Timestamp(before)
    latest = df.loc[df["hg"].notna(), "date"].max()
    return {
        "scope": SCOPE,
        "data_through": latest.strftime("%Y-%m-%d") if pd.notna(latest) else None,
        "home_form": team_form(df, home, before, model),
        "away_form": team_form(df, away, before, model),
        "home_at_home": venue_form(df, home, "home", before, model=model),
        "away_away": venue_form(df, away, "away", before, model=model),
        "h2h": head_to_head(df, home, away, before),
        "rest_days": {"home": rest_days(df, home, before, other, as_of),
                      "away": rest_days(df, away, before, other, as_of)},
        "last_match": {side: _jsonable(last_match(df, team, before, other))
                       for side, team in (("home", home), ("away", away))},
        "rest_scope": ("league, cup and continental matches" if other is not None
                       else "league matches only"),
    }


def _jsonable(m):
    return None if m is None else {**m, "date": m["date"].strftime("%Y-%m-%d")}
