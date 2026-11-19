"""
engine/results.py
=================
Final scores from ESPN's public scoreboard (all competitions it covers), used to
grade predictions in leagues football-data.co.uk does not cover and for days it
has not published yet. No odds and no half-time scores.

Matches decided after extra time or penalties are stored with status "aet"/"pen": they
count for rest days, but grading and the ratings only use 90-minute results ("ft"),
because bets settle on the 90-minute score.
"""
import datetime
import json
import os

import pandas as pd
import requests

from engine.data import HEADERS

URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "results")

# ESPN league slug -> football-data code
ESPN_TO_FD = {
    "eng.1": "E0", "eng.2": "E1", "eng.3": "E2", "eng.4": "E3", "eng.5": "EC",
    "sco.1": "SC0", "sco.2": "SC1", "sco.3": "SC2", "sco.4": "SC3",
    "ger.1": "D1", "ger.2": "D2", "ita.1": "I1", "ita.2": "I2", "esp.1": "SP1", "esp.2": "SP2",
    "fra.1": "F1", "fra.2": "F2", "ned.1": "N1", "bel.1": "B1", "por.1": "P1", "tur.1": "T1",
    "gre.1": "G1", "arg.1": "ARG", "aut.1": "AUT", "bra.1": "BRA", "chn.1": "CHN", "den.1": "DNK",
    "fin.1": "FIN", "irl.1": "IRL", "jpn.1": "JPN", "mex.1": "MEX", "nor.1": "NOR", "pol.1": "POL",
    "rou.1": "ROU", "rus.1": "RUS", "swe.1": "SWE", "sui.1": "SWZ", "usa.1": "USA",
}


# ESPN status -> stored status
_STATUS = {"STATUS_FULL_TIME": "ft", "STATUS_FINAL_AET": "aet", "STATUS_FINAL_PEN": "pen"}

# Country (engine/data.py LEAGUES) -> ESPN slug prefix, and the continental club competitions its teams play
COUNTRY_ESPN = {
    "england": "eng", "scotland": "sco", "germany": "ger", "italy": "ita", "spain": "esp", "france": "fra",
    "netherlands": "ned", "belgium": "bel", "portugal": "por", "turkey": "tur", "greece": "gre",
    "argentina": "arg", "austria": "aut", "brazil": "bra", "china": "chn", "denmark": "den", "finland": "fin",
    "ireland": "irl", "japan": "jpn", "mexico": "mex", "norway": "nor", "poland": "pol", "romania": "rou",
    "russia": "rus", "sweden": "swe", "switzerland": "sui", "usa": "usa",
}
CONTINENT = {"argentina": "conmebol", "brazil": "conmebol", "usa": "concacaf", "mexico": "concacaf",
             "japan": "afc", "china": "afc"}                           # everyone else: "uefa"


def _day(d: datetime.date) -> list[dict]:
    path = os.path.join(CACHE_DIR, f"espn2_{d:%Y%m%d}.json")
    finished_day = d < datetime.date.today() - datetime.timedelta(days=1)
    if os.path.exists(path) and finished_day:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    try:
        r = requests.get(URL, params={"dates": f"{d:%Y%m%d}", "limit": 1000}, headers=HEADERS, timeout=30)
        r.raise_for_status()
        events = r.json().get("events", [])
    except (requests.RequestException, ValueError) as e:
        print(f"  [Results] ESPN {d}: {e}")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return []

    rows = []
    for ev in events:
        comp = ev["competitions"][0]
        status = _STATUS.get(comp["status"]["type"]["name"])
        if status is None:                       # not finished (or postponed/abandoned)
            continue
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        if "home" not in teams or "away" not in teams:
            continue
        slug = next((l["href"].split("/league/")[1].split("/")[0]
                     for l in ev.get("links", []) if "/league/" in l.get("href", "")), "")
        rows.append({
            "date": ev["date"][:10],
            "home": teams["home"]["team"]["displayName"].strip(),
            "away": teams["away"]["team"]["displayName"].strip(),
            "hg": int(teams["home"]["score"]), "ag": int(teams["away"]["score"]),
            "competition": ev.get("season", {}).get("slug", ""),
            "slug": slug,
            "status": status,
        })
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    return rows


def recent_league_results(fd: pd.DataFrame, codes: list[str], days: int = 14) -> pd.DataFrame:
    """
    ESPN league results from the last `days` days that football-data (`fd`) has not
    published yet, with team names mapped to fd names. football-data usually lags
    a few days, so without this the ratings miss the latest round.
    """
    from engine.data import match_team

    today = datetime.date.today()
    espn = espn_results(today - datetime.timedelta(days=days), today)
    espn = espn[espn["league"].isin(codes)]
    if espn.empty or fd.empty:
        return pd.DataFrame()
    teams = sorted(set(fd["home"]) | set(fd["away"]))
    played = fd.dropna(subset=["hg"])
    known = {(r.home, r.away, r.date.normalize()) for r in played[played["date"] >= pd.Timestamp(
        today - datetime.timedelta(days=days + 2))].itertuples()}
    rows = []
    for r in espn.itertuples():
        h, _ = match_team(r.home, teams)
        a, _ = match_team(r.away, teams)
        if not h or not a or h == a:
            continue
        d = r.date.normalize()
        if any((h, a, d + pd.Timedelta(days=k)) in known for k in (-1, 0, 1)):
            continue
        rows.append({"date": r.date, "home": h, "away": a, "hg": r.hg, "ag": r.ag, "league": r.league})
    return pd.DataFrame(rows)


def espn_results(start: datetime.date, end: datetime.date, include_extra_time: bool = False) -> pd.DataFrame:
    """Finished matches; by default only those decided in 90 minutes (what bets settle on)."""
    rows = []
    d = start
    while d <= end:
        rows.extend(_day(d))
        d += datetime.timedelta(days=1)
    df = pd.DataFrame(rows, columns=["date", "home", "away", "hg", "ag", "competition", "slug", "status"])
    df["status"] = df["status"].fillna("ft")
    if not include_extra_time:
        df = df[df["status"] == "ft"]
    df["date"] = pd.to_datetime(df["date"])
    df["league"] = df["slug"].map(ESPN_TO_FD)
    return df.reset_index(drop=True)


def recent_other_matches(country: str, teams: list[str], days: int = 14) -> pd.DataFrame:
    """
    Cup and continental matches (not in the league data) played by `country`'s teams in the
    last `days` days: one row per team appearance, with football-data team names.

    Only competitions this country's clubs can play in are scanned (its own cups, plus UEFA /
    CONMEBOL / CONCACAF / AFC club competitions), and names are matched against this country's
    own team list, so Ecuador's "Barcelona SC" is never taken for Spain's Barcelona.
    """
    from engine.data import match_team

    prefix = COUNTRY_ESPN.get(country)
    if not prefix or not teams:
        return pd.DataFrame(columns=["date", "team", "opponent", "competition", "slug"])
    today = datetime.date.today()
    e = espn_results(today - datetime.timedelta(days=days), today, include_extra_time=True)
    cont = CONTINENT.get(country, "uefa")
    slug = e["slug"].fillna("")
    mask = ((slug.str.startswith(prefix + ".") | slug.str.startswith(cont + "."))
            & ~slug.isin(list(ESPN_TO_FD)) & ~slug.str.contains(r"\.w\.|women|wom", regex=True))
    rows = []
    for r in e[mask].itertuples():
        for name, opp in ((r.home, r.away), (r.away, r.home)):
            t, _ = match_team(name, teams)
            if t:
                rows.append({"date": r.date, "team": t, "opponent": opp, "competition": r.slug,
                             "slug": r.slug})
    return pd.DataFrame(rows, columns=["date", "team", "opponent", "competition", "slug"])
