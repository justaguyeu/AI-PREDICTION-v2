"""
engine/data.py
==============
Historical match results + bookmaker odds from football-data.co.uk (free CSVs).

  - Main leagues : https://www.football-data.co.uk/mmz4281/{season}/{code}.csv
  - Extra leagues: https://www.football-data.co.uk/new/{code}.csv  (all seasons in one file)

Files are cached in data/cache/. Current-season files are refreshed every
CACHE_HOURS; finished seasons are downloaded once.
"""
import datetime
import io
import os
import re
import time
import unicodedata
from difflib import SequenceMatcher

import pandas as pd
import requests

BASE = "https://football-data.co.uk"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")
CACHE_HOURS = 12
HEADERS = {"User-Agent": "Mozilla/5.0 (football-predictor)"}

# code -> (kind, country, exact league names as they may appear on BetPawa, lower case,
# text before any comma: "Liga MX, Apertura" -> "liga mx"). Names must match exactly:
# substring matching sent "Northern Premier League" to the Premier League.
LEAGUES = {
    "E0":  ("main",  "england",     ["premier league"]),
    "E1":  ("main",  "england",     ["championship"]),
    "E2":  ("main",  "england",     ["league one", "league 1"]),
    "E3":  ("main",  "england",     ["league two", "league 2"]),
    "EC":  ("main",  "england",     ["national league"]),
    "SC0": ("main",  "scotland",    ["premiership", "premier league"]),
    "SC1": ("main",  "scotland",    ["championship"]),
    "SC2": ("main",  "scotland",    ["league one", "league 1"]),
    "SC3": ("main",  "scotland",    ["league two", "league 2"]),
    "D2":  ("main",  "germany",     ["2. bundesliga", "2 bundesliga", "bundesliga 2"]),
    "D1":  ("main",  "germany",     ["bundesliga"]),
    "I2":  ("main",  "italy",       ["serie b"]),
    "I1":  ("main",  "italy",       ["serie a"]),
    "SP2": ("main",  "spain",       ["laliga 2", "la liga 2", "segunda division", "laliga hypermotion"]),
    "SP1": ("main",  "spain",       ["laliga", "la liga", "primera division", "laliga ea sports"]),
    "F2":  ("main",  "france",      ["ligue 2"]),
    "F1":  ("main",  "france",      ["ligue 1"]),
    "N1":  ("main",  "netherlands", ["eredivisie"]),
    "B1":  ("main",  "belgium",     ["pro league", "first division a", "jupiler pro league"]),
    "P1":  ("main",  "portugal",    ["primeira liga", "liga portugal", "liga portugal betclic"]),
    "T1":  ("main",  "turkey",      ["super lig", "süper lig", "superlig", "super league"]),
    "G1":  ("main",  "greece",      ["super league", "super league 1"]),
    "ARG": ("extra", "argentina",   ["liga profesional", "primera division", "superliga", "torneo betano"]),
    "AUT": ("extra", "austria",     ["bundesliga"]),
    "BRA": ("extra", "brazil",      ["serie a", "brasileiro serie a", "brasileirao serie a"]),
    "CHN": ("extra", "china",       ["super league", "chinese super league"]),
    "DNK": ("extra", "denmark",     ["superliga", "superligaen"]),
    "FIN": ("extra", "finland",     ["veikkausliiga"]),
    "IRL": ("extra", "ireland",     ["premier division", "premier league"]),
    "JPN": ("extra", "japan",       ["j1 league", "j.league", "j. league", "j-league", "j league", "j1"]),
    "MEX": ("extra", "mexico",      ["liga mx", "primera division"]),
    "NOR": ("extra", "norway",      ["eliteserien"]),
    "POL": ("extra", "poland",      ["ekstraklasa"]),
    "ROU": ("extra", "romania",     ["liga 1", "liga i", "superliga"]),
    "RUS": ("extra", "russia",      ["premier league"]),
    "SWE": ("extra", "sweden",      ["allsvenskan"]),
    "SWZ": ("extra", "switzerland", ["super league"]),
    "USA": ("extra", "usa",         ["mls", "major league soccer"]),
}

COUNTRY_ALIASES = {"england": ["england"], "usa": ["usa", "united states"], "turkey": ["turkey", "türkiye", "turkiye"]}
EXCLUDE_WORDS = ("women", "u17", "u18", "u19", "u20", "u21", "u23", "reserve", "youth", "amateur")


def season_code(date: datetime.date) -> str:
    """football-data season code, e.g. 2026-10-13 -> '2627'."""
    start = date.year if date.month >= 7 else date.year - 1
    return f"{start % 100:02d}{(start + 1) % 100:02d}"


def resolve_league(league_str: str | None) -> tuple[list[str], bool]:
    """
    Map a BetPawa league string like 'Football / England / Premier League'
    to football-data codes. Returns (codes, exact):
      exact=True  -> one league matched by name
      exact=False -> only the country matched (cups etc.): all leagues of that country
    """
    if not league_str:
        return [], False
    s = league_str.lower()
    if any(w in s for w in EXCLUDE_WORDS):
        return [], False
    parts = [p.strip() for p in s.split("/")]
    if parts and parts[0] == "football":
        parts = parts[1:]
    country = parts[0] if len(parts) > 1 else ""
    name = parts[-1].split(",")[0].strip()

    in_country = [c for c, (_, ctry, _) in LEAGUES.items()
                  if ctry == country or country in COUNTRY_ALIASES.get(ctry, [])]
    for code in in_country:
        if name in LEAGUES[code][2]:
            return [code], True
    # Cups and leagues we have no data for: the caller may still find both teams in the
    # country's data (FA Cup ties between league clubs), as long as they are current.
    return in_country, False


# ── Downloading ──────────────────────────────────────────────────────────────

def _fetch(url: str, path: str, max_age_hours: float | None) -> str | None:
    if os.path.exists(path):
        age_h = (time.time() - os.path.getmtime(path)) / 3600
        if max_age_hours is None or age_h < max_age_hours:
            return path
    for attempt in range(2):
        try:
            r = requests.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200 and len(r.content) > 200 and b"<html" not in r.content[:500].lower():
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(r.content)
                return path
            break
        except requests.RequestException as e:
            if attempt:
                print(f"  [Data] Download failed {url}: {e}")
    return path if os.path.exists(path) else None  # stale cache beats nothing


def _read_csv(path: str) -> pd.DataFrame:
    with open(path, "rb") as f:
        raw = f.read().decode("utf-8-sig", errors="replace")
    return pd.read_csv(io.StringIO(raw), on_bad_lines="skip", low_memory=False)


def _col(df, *names):
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce")
    return pd.Series(float("nan"), index=df.index)


def _normalise_frame(df: pd.DataFrame, code: str, kind: str) -> pd.DataFrame:
    if kind == "main":
        home, away, hg, ag = "HomeTeam", "AwayTeam", "FTHG", "FTAG"
    else:
        home, away, hg, ag = "Home", "Away", "HG", "AG"
    if home not in df.columns:
        return pd.DataFrame()
    out = pd.DataFrame({
        "date": pd.to_datetime(df["Date"], dayfirst=True, errors="coerce", format="mixed"),
        "home": df[home].astype(str).str.strip(),
        "away": df[away].astype(str).str.strip(),
        "hg": _col(df, hg),
        "ag": _col(df, ag),
        "hthg": _col(df, "HTHG"),
        "htag": _col(df, "HTAG"),
        # pre-closing average odds where available, otherwise closing
        "oh": _col(df, "AvgH", "BbAvH", "AvgCH", "PSCH", "B365H"),
        "od": _col(df, "AvgD", "BbAvD", "AvgCD", "PSCD", "B365D"),
        "oa": _col(df, "AvgA", "BbAvA", "AvgCA", "PSCA", "B365A"),
        "o_over25": _col(df, "Avg>2.5", "BbAv>2.5", "AvgC>2.5"),
        "o_under25": _col(df, "Avg<2.5", "BbAv<2.5", "AvgC<2.5"),
        # expected goals (main leagues from 2026/27) and shots on target (main leagues)
        "hxg": _col(df, "HxG"),
        "axg": _col(df, "AxG"),
        "hst": _col(df, "HST"),
        "ast": _col(df, "AST"),
    })
    out["league"] = code
    return out.dropna(subset=["date"])


def load_league(code: str, today: datetime.date | None = None, seasons: int = 2) -> pd.DataFrame:
    """All matches (played and scheduled) for a league over the last `seasons` seasons."""
    today = today or datetime.date.today()
    kind = LEAGUES[code][0]
    frames = []
    if kind == "main":
        start_year = today.year if today.month >= 7 else today.year - 1
        for i in range(seasons):
            y = start_year - i
            sc = f"{y % 100:02d}{(y + 1) % 100:02d}"
            current = (i == 0)
            path = _fetch(f"{BASE}/mmz4281/{sc}/{code}.csv",
                          os.path.join(CACHE_DIR, f"{code}_{sc}.csv"),
                          CACHE_HOURS if current else None)
            if path:
                frames.append(_normalise_frame(_read_csv(path), code, kind))
    else:
        path = _fetch(f"{BASE}/new/{code}.csv", os.path.join(CACHE_DIR, f"{code}.csv"), CACHE_HOURS)
        if path:
            df = _normalise_frame(_read_csv(path), code, kind)
            cutoff = pd.Timestamp(today) - pd.Timedelta(days=365 * seasons + 60)
            frames.append(df[df["date"] >= cutoff])
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


def country_codes(code: str) -> list[str]:
    """All football-data leagues of the same country (connected through promotion/relegation)."""
    country = LEAGUES[code][1]
    return [c for c, (_, ctry, _) in LEAGUES.items() if ctry == country]


def load_country(code: str, today: datetime.date | None = None, seasons: int = 2) -> pd.DataFrame:
    """Matches of every division in `code`'s country, so ratings carry across promotion."""
    frames = [load_league(c, today, seasons) for c in country_codes(code)]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values("date").reset_index(drop=True)


# ── Team-name matching ───────────────────────────────────────────────────────

# BetPawa/common name -> football-data name (normalised form on both sides)
ALIASES = {
    "manchester united": "man united", "manchester utd": "man united", "man utd": "man united",
    "manchester city": "man city",
    "tottenham hotspur": "tottenham", "spurs": "tottenham",
    "wolverhampton": "wolves", "wolverhampton wanderers": "wolves",
    "nottingham forest": "nottm forest", "nottingham": "nottm forest",
    "brighton hove albion": "brighton", "brighton and hove albion": "brighton",
    "west ham united": "west ham", "newcastle united": "newcastle",
    "leeds united": "leeds", "sheffield united": "sheffield united",
    "sheffield wednesday": "sheffield weds", "queens park rangers": "qpr",
    "west bromwich albion": "west brom", "west bromwich": "west brom",
    "paris saint germain": "paris sg", "psg": "paris sg", "paris sg": "paris sg",
    "olympique lyon": "lyon", "olympique lyonnais": "lyon",
    "olympique marseille": "marseille", "racing club de lens": "lens", "rc lens": "lens",
    "stade rennais": "rennes", "as saint etienne": "st etienne", "saint etienne": "st etienne",
    "bayern munchen": "bayern munich", "fc bayern munchen": "bayern munich",
    "borussia monchengladbach": "mgladbach", "monchengladbach": "mgladbach",
    "borussia dortmund": "dortmund", "bayer leverkusen": "leverkusen", "bayer 04 leverkusen": "leverkusen",
    "eintracht frankfurt": "ein frankfurt", "rb leipzig": "rb leipzig", "rasenballsport leipzig": "rb leipzig",
    "1 fc koln": "fc koln", "koln": "fc koln", "cologne": "fc koln",
    "1 fc cologne": "fc koln", "fc cologne": "fc koln",
    "1 fc nuremberg": "nurnberg", "1 fc nurnberg": "nurnberg", "nuremberg": "nurnberg",
    "vfb stuttgart": "stuttgart", "vfl wolfsburg": "wolfsburg", "werder bremen": "werder bremen",
    "inter milan": "inter", "internazionale": "inter", "inter milano": "inter",
    "ac milan": "milan", "as roma": "roma", "ss lazio": "lazio", "ssc napoli": "napoli",
    "atletico madrid": "ath madrid", "atletico de madrid": "ath madrid",
    "athletic bilbao": "ath bilbao", "athletic club": "ath bilbao",
    "real betis": "betis", "real sociedad": "sociedad", "celta vigo": "celta", "rcd espanyol": "espanol",
    "espanyol": "espanol", "deportivo alaves": "alaves", "rayo vallecano": "vallecano",
    "psv eindhoven": "psv eindhoven", "az alkmaar": "az alkmaar", "sporting cp": "sp lisbon",
    "sporting lisbon": "sp lisbon", "sporting braga": "braga", "sc braga": "braga",
    "vitoria guimaraes": "guimaraes", "fc porto": "porto", "sl benfica": "benfica",
    # reserve sides known by brand names (no "B" in the name)
    "urawa red diamonds": "urawa reds",
    "deportivo": "la coruna", "deportivo la coruna": "la coruna", "rc deportivo": "la coruna",
    "celta fortuna": "celta b", "rc celta fortuna": "celta b", "sanse": "sociedad b",
    "real madrid castilla": "real madrid b", "castilla": "real madrid b",
    "barcelona atletic": "barcelona b", "bilbao athletic": "ath bilbao b",
}

# Tokens that carry no identity ("FC", "1893", "Club"...)
_STOP = {"fc", "cf", "sc", "afc", "ac", "club", "de", "the", "cd", "ud", "sd", "rc", "ssc", "as", "ss",
         "sv", "fk", "sk", "if", "bk", "ff", "kv", "krc", "rsc", "us", "calcio", "1", "cfc",
         "football", "futbol", "clube", "sporting club", "rks", "mks", "ks", "tsg", "vfl", "vfb",
         "fsv", "spvgg", "sad", "ca", "ec", "se", "cr"}


# Words that make a different team: "Ipswich Town U21" must never match "Ipswich".
_QUALIFIER_SYNONYMS = {
    "women": "women", "ladies": "women", "fem": "women", "femenino": "women", "feminino": "women",
    "feminine": "women", "u17": "u17", "u18": "u18", "u19": "u19", "u20": "u20", "u21": "u21",
    "u22": "u22", "u23": "u23", "b": "b", "ii": "b", "reserve": "reserves", "reserves": "reserves",
    "youth": "youth", "academy": "youth",
}


def normalise_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((w|f|women|fem)\)", " women ", s)
    s = re.sub(r"\([a-z]{1,3}\)", " ", s)    # country codes: "AL Ahly SC (EGY)" -> "al ahly sc"
    s = re.sub(r"[()]", " ", s)              # but keep places: "Gimnasia (Mendoza)" -> "gimnasia mendoza"
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(18|19|20)\d{2}\b", " ", s)  # founding years
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r" w$", " women", s)         # "Arsenal W"
    return ALIASES.get(s, s)


def _qualifiers(s: str) -> set[str]:
    return {_QUALIFIER_SYNONYMS[t] for t in s.split() if t in _QUALIFIER_SYNONYMS}


def _tokens(s: str) -> list[str]:
    return [t for t in s.split() if t not in _STOP and t not in _QUALIFIER_SYNONYMS]


# Words shared by many different clubs. Sharing only these is no evidence of the same team:
# "Al Zawraa" is not "Al Fateh", "St Mirren" is not "St Johnstone", "Real Madrid" is not "Real Betis".
_GENERIC = {
    "al", "el", "real", "united", "city", "town", "sporting", "racing", "athletic", "atletico", "athletico",
    "club", "clube", "deportivo", "dynamo", "dinamo", "inter", "union", "hapoel", "maccabi", "beitar", "ironi",
    "olympique", "olympic", "sport", "sports", "esporte", "st", "saint", "san", "santa", "of", "de", "la", "le",
    "del", "the", "and", "rovers", "wanderers", "county", "albion", "young", "boys", "men", "stars", "star",
    "new", "north", "south", "east", "west", "royal", "ltd", "limited", "sfc", "nk", "bsc", "cd", "cf",
    "juniors", "jrs", "jr",
}


def _tok_eq(a: str, b: str, abbrev: bool = True) -> bool:
    if len(a) == 1 or len(b) == 1:               # abbreviation: "Inverness C" / "Gimnasia L.P."
        return abbrev and a[0] == b[0]
    if a == b:
        return True
    if len(a) <= 3 or len(b) <= 3:
        return False
    # spelling variants: "Vasteraas"/"Vasteras", "Bodoe"/"Bodo", "Hamburger"/"Hamburg", "Krylia"/"Krylya";
    # but "America" is not "Almeria" (same letters, different start)
    r = SequenceMatcher(None, a, b).ratio()
    return r >= 0.9 or (r >= 0.82 and a[:3] == b[:3])


def _similarity(a: str, b: str) -> float:
    """
    Token-level score: names match only when every distinctive word of the shorter
    name appears (fuzzily) in the longer one; generic words ("Al", "Real", "St",
    "United") alone never make a match. Matching first words get a bonus
    ("Grasshopper Club Zurich" -> "Grasshoppers", not "Zurich").
    """
    if a == b:
        return 1.1
    if _qualifiers(a) != _qualifiers(b):
        return 0.0
    full = SequenceMatcher(None, a, b).ratio()
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.9 * full
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    found = [any(_tok_eq(t, u) for u in long_) for t in short]
    distinctive = [f for t, f in zip(short, found) if t not in _GENERIC]
    if not all(distinctive if distinctive else found):
        return 0.9 * full
    # an abbreviation may complete a match but never be the only evidence for it:
    # "Fukushima United" must not match "Yokohama F. Marinos" through the "F"
    if distinctive and not any(any(_tok_eq(t, u, abbrev=False) for u in long_)
                               for t in short if t not in _GENERIC and len(t) > 1):
        return 0.9 * full
    weight = [0.5 if t in _GENERIC else 1.0 for t in short]          # generic words count half
    score = 0.6 + 0.35 * sum(w for w, f in zip(weight, found) if f) / sum(weight)
    if _tok_eq(ta[0], tb[0]):
        score += 0.05
    unmatched_long = sum(not any(_tok_eq(u, t) for t in short) for u in long_)
    return score - 0.01 * unmatched_long + 0.01 * full


def match_team(name: str, candidates: list[str], threshold: float = 0.8) -> tuple[str | None, float]:
    """Best football-data team name for `name` among `candidates`."""
    target = normalise_name(name)
    best, best_score = None, 0.0
    for c in candidates:
        sc = _similarity(target, normalise_name(c))
        if sc > best_score:
            best, best_score = c, sc
    return (best, best_score) if best_score >= threshold else (None, best_score)
