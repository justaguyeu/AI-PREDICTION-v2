"""
engine/dixon_coles.py
=====================
Dixon & Coles (1997) bivariate-Poisson model with time decay.

  log λ_home = c + home_adv + att[home] + def[away]
  log μ_away = c            + att[away] + def[home]

`def` is defensive weakness (higher = concedes more). Low scorelines (0-0, 1-0,
0-1, 1-1) are corrected with the ρ term. Matches are weighted by exp(-xi * days_ago),
and attack/defence ratings get an L2 prior toward the league average so teams with
few games (promoted sides, start of season) are not over-fitted.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.stats import poisson

XI = 0.0019          # time decay per day (half-life ≈ 1 year); see backtest.py
REG = 0.25           # L2 prior strength on ratings (backtest: 0.1-0.5 best, 2.0 under-confident)
MAX_DAYS = 730
XG_WEIGHT = 0.3      # share of xG in goal targets (main leagues from 2026/27). Walk-forward on 970 matches:
                     # model log-loss 1.0330 -> 1.0305, gain 95% interval +0.0002..+0.0049; see README
MAX_GOALS = 10


@dataclass
class DCModel:
    league: str
    teams: list[str]
    attack: dict[str, float]
    defence: dict[str, float]
    intercept: float
    home_adv: float
    rho: float
    games: dict[str, float] = field(default_factory=dict)   # weighted games per team
    recent: dict[str, int] = field(default_factory=dict)    # matches in last 365 days
    days_idle: dict[str, int] = field(default_factory=dict)  # days between team's last match and the data's last match

    def is_current(self, team: str, max_idle: int = 45) -> bool:
        """False for teams that dropped out of the covered divisions (relegated to non-league etc.)."""
        return self.days_idle.get(team, 10_000) <= max_idle

    def rates(self, home: str, away: str) -> tuple[float, float]:
        lam = np.exp(self.intercept + self.home_adv + self.attack[home] + self.defence[away])
        mu = np.exp(self.intercept + self.attack[away] + self.defence[home])
        return float(lam), float(mu)

    def team_goals(self, team: str) -> tuple[float, float]:
        """Expected goals scored / conceded per game vs an average side (neutral venue)."""
        base = self.intercept + self.home_adv / 2
        return float(np.exp(base + self.attack[team])), float(np.exp(base + self.defence[team]))


def score_matrix(lam: float, mu: float, rho: float = 0.0, max_goals: int = MAX_GOALS) -> np.ndarray:
    """P[h, a] for h, a in 0..max_goals-1 with Dixon-Coles low-score correction."""
    k = np.arange(max_goals)
    m = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
    m[0, 0] *= max(1 - lam * mu * rho, 1e-10)
    m[0, 1] *= max(1 + lam * rho, 1e-10)
    m[1, 0] *= max(1 + mu * rho, 1e-10)
    m[1, 1] *= max(1 - rho, 1e-10)
    return m / m.sum()


def fit(matches: pd.DataFrame, ref_date=None, xi: float = XI, reg: float = REG,
        league: str = "", xg_weight: float = XG_WEIGHT) -> DCModel | None:
    """
    Fit on played matches strictly before ref_date (default: all played matches).
    xg_weight > 0 replaces goals by (1-w)*goals + w*xG in the Poisson terms for matches
    that have xG (low-score correction still uses actual goals).
    """
    df = matches.dropna(subset=["hg", "ag"])
    ref = pd.Timestamp(ref_date) if ref_date is not None else df["date"].max() + pd.Timedelta(days=1)
    df = df[(df["date"] < ref) & (df["date"] >= ref - pd.Timedelta(days=MAX_DAYS))]
    if len(df) < 30:
        return None

    teams = sorted(set(df["home"]) | set(df["away"]))
    idx = {t: i for i, t in enumerate(teams)}
    n = len(teams)
    hi = df["home"].map(idx).to_numpy()
    ai = df["away"].map(idx).to_numpy()
    hg = df["hg"].to_numpy(dtype=float)
    ag = df["ag"].to_numpy(dtype=float)
    th, ta = hg, ag                       # Poisson targets
    if xg_weight and "hxg" in df.columns:
        hx, ax = df["hxg"].to_numpy(dtype=float), df["axg"].to_numpy(dtype=float)
        ok = np.isfinite(hx) & np.isfinite(ax)
        th = np.where(ok, (1 - xg_weight) * hg + xg_weight * hx, hg)
        ta = np.where(ok, (1 - xg_weight) * ag + xg_weight * ax, ag)
    days = (ref - df["date"]).dt.days.to_numpy(dtype=float)
    w = np.exp(-xi * days)

    m00 = (hg == 0) & (ag == 0)
    m01 = (hg == 0) & (ag == 1)
    m10 = (hg == 1) & (ag == 0)
    m11 = (hg == 1) & (ag == 1)

    def nll(p):
        att, dfn, c, home, rho = p[:n], p[n:2 * n], p[2 * n], p[2 * n + 1], p[2 * n + 2]
        log_lam = c + home + att[hi] + dfn[ai]
        log_mu = c + att[ai] + dfn[hi]
        lam, mu = np.exp(log_lam), np.exp(log_mu)

        tau = np.ones_like(lam)
        tau[m00] = 1 - lam[m00] * mu[m00] * rho
        tau[m01] = 1 + lam[m01] * rho
        tau[m10] = 1 + mu[m10] * rho
        tau[m11] = 1 - rho
        tau = np.maximum(tau, 1e-10)

        ll = w * (np.log(tau) + th * log_lam - lam + ta * log_mu - mu)
        loss = -ll.sum() + reg * (att @ att + dfn @ dfn)

        # gradients w.r.t. log λ, log μ, ρ
        g_lam = th - lam
        g_mu = ta - mu
        g_rho = np.zeros_like(lam)
        g_lam[m00] += -lam[m00] * mu[m00] * rho / tau[m00]
        g_mu[m00] += -lam[m00] * mu[m00] * rho / tau[m00]
        g_rho[m00] = -lam[m00] * mu[m00] / tau[m00]
        g_lam[m01] += lam[m01] * rho / tau[m01]
        g_rho[m01] = lam[m01] / tau[m01]
        g_mu[m10] += mu[m10] * rho / tau[m10]
        g_rho[m10] = mu[m10] / tau[m10]
        g_rho[m11] = -1 / tau[m11]
        g_lam, g_mu, g_rho = w * g_lam, w * g_mu, w * g_rho

        g_att = np.bincount(hi, g_lam, n) + np.bincount(ai, g_mu, n)
        g_def = np.bincount(ai, g_lam, n) + np.bincount(hi, g_mu, n)
        grad = np.concatenate([
            -g_att + 2 * reg * att,
            -g_def + 2 * reg * dfn,
            [-(g_lam.sum() + g_mu.sum()), -g_lam.sum(), -g_rho.sum()],
        ])
        return loss, grad

    mean_goals = max((th * w).sum() / w.sum() / 2 + (ta * w).sum() / w.sum() / 2, 0.3)
    x0 = np.concatenate([np.zeros(2 * n), [np.log(mean_goals), 0.2, -0.05]])
    bounds = [(-3, 3)] * (2 * n) + [(-3, 3), (-1, 1), (-0.25, 0.25)]
    res = minimize(nll, x0, jac=True, method="L-BFGS-B", bounds=bounds)
    p = res.x

    games = np.bincount(hi, w, n) + np.bincount(ai, w, n)
    recent_mask = days <= 365
    recent = np.bincount(hi[recent_mask], minlength=n) + np.bincount(ai[recent_mask], minlength=n)
    return DCModel(
        league=league, teams=teams,
        attack={t: float(p[i]) for t, i in idx.items()},
        defence={t: float(p[n + i]) for t, i in idx.items()},
        intercept=float(p[2 * n]), home_adv=float(p[2 * n + 1]), rho=float(p[2 * n + 2]),
        games={t: float(games[i]) for t, i in idx.items()},
        recent={t: int(recent[i]) for t, i in idx.items()},
        days_idle={t: int(d) for t, d in (
            pd.concat([df[["date", "home"]].rename(columns={"home": "team"}),
                       df[["date", "away"]].rename(columns={"away": "team"})])
            .groupby("team")["date"].max().rsub(df["date"].max()).dt.days.items())},
    )
