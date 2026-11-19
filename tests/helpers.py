"""Synthetic data shared by the tests (no network, no files under data/)."""
import numpy as np
import pandas as pd

from engine import dixon_coles as dc

TRUE_HOME_ADV = 0.25


def synthetic_league(n_teams: int = 16, seasons: int = 2, seed: int = 1, end: str = "2026-10-01"):
    """Double round-robin seasons of Poisson scores from known team strengths."""
    rng = np.random.default_rng(seed)
    teams = [f"Team {i:02d}" for i in range(n_teams)]
    att = dict(zip(teams, rng.normal(0, 0.3, n_teams)))
    dfn = dict(zip(teams, rng.normal(0, 0.3, n_teams)))
    c = np.log(1.3)
    fixtures = [(h, a) for h in teams for a in teams if h != a] * seasons
    rng.shuffle(fixtures)
    dates = pd.date_range(end=end, periods=len(fixtures), freq="D")
    rows = []
    for d, (h, a) in zip(dates, fixtures):
        lam = np.exp(c + TRUE_HOME_ADV + att[h] + dfn[a])
        mu = np.exp(c + att[a] + dfn[h])
        rows.append({"date": d, "home": h, "away": a, "hg": rng.poisson(lam), "ag": rng.poisson(mu),
                     "league": "E0", "hthg": np.nan, "htag": np.nan,
                     "oh": np.nan, "od": np.nan, "oa": np.nan, "hxg": np.nan, "axg": np.nan})
    return pd.DataFrame(rows), att, dfn


_MODEL_CACHE = {}


def fitted_model():
    if "m" not in _MODEL_CACHE:
        df, att, dfn = synthetic_league()
        _MODEL_CACHE["m"] = (dc.fit(df, league="E0"), df, att, dfn)
    return _MODEL_CACHE["m"]
