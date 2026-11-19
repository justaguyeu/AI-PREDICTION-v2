"""
engine/market.py
================
Bookmaker odds -> fair probabilities, model/market blending, and solving for
goal rates (λ, μ) that reproduce a target 1X2 distribution.
"""
import math

import numpy as np
from scipy.optimize import least_squares

from engine.dixon_coles import score_matrix

# Weight on the bookmaker in the log-linear pool when valid odds exist. Walk-forward test on 7,230
# matches (16 leagues, Aug 2025 - Oct 2026): every weight below 1.0 made the 1X2 probabilities worse,
# also against a single bookmaker's odds (Bet365, 7.3% margin): log-loss 1.0034 at 1.0, 1.0041 at 0.9,
# 1.0086 at 0.6 (95% intervals exclude zero). The results model is used when there are no valid odds,
# as a cross-check, and for context; it does not move the probabilities when odds are available.
MARKET_WEIGHT = 1.0


def valid_overround(total_implied: float) -> bool:
    """
    Real 1X2 odds always imply more than 100% (the margin). Below 100% means an arbitrage,
    which in practice is a data error (football-data has a few such rows; a mis-scraped page
    could produce one); above 135% is not a normal football 1X2 market either.
    """
    return 1.0 < total_implied <= 1.35


def overround(odds) -> float | None:
    try:
        return float(sum(1.0 / float(x) for x in odds))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def implied_probs(odds) -> np.ndarray | None:
    """
    Remove the bookmaker margin with the power method (p_i = (1/o_i)^k, Σp = 1),
    which corrects the favourite-longshot bias better than simple normalising.
    """
    if odds is None:
        return None
    try:
        o = np.array([float(x) for x in odds], dtype=float)
    except (TypeError, ValueError):
        return None
    if len(o) != 3 or not np.all(np.isfinite(o)) or np.any(o <= 1.0):
        return None
    inv = 1.0 / o
    if not valid_overround(inv.sum()):
        return None
    lo, hi = 0.5, 3.0
    for _ in range(60):
        k = (lo + hi) / 2
        if (inv ** k).sum() > 1:
            lo = k
        else:
            hi = k
    p = inv ** ((lo + hi) / 2)
    return p / p.sum()


def blend(p_model, p_market, w: float = MARKET_WEIGHT) -> np.ndarray:
    """Log-linear pool: p ∝ p_model^(1-w) · p_market^w."""
    if p_market is None:
        return np.asarray(p_model)
    if p_model is None:
        return np.asarray(p_market)
    lp = (1 - w) * np.log(np.clip(p_model, 1e-9, 1)) + w * np.log(np.clip(p_market, 1e-9, 1))
    p = np.exp(lp - lp.max())
    return p / p.sum()


def outcome_probs(m: np.ndarray) -> np.ndarray:
    return np.array([np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()])


def rates_from_1x2(p1x2, rho: float = -0.05, start=(1.4, 1.1)) -> tuple[float, float]:
    """Find (λ, μ) whose Dixon-Coles score matrix gives the target home/away win probabilities."""
    target = np.asarray(p1x2)

    def resid(x):
        lam, mu = math.exp(x[0]), math.exp(x[1])
        p = outcome_probs(score_matrix(lam, mu, rho))
        return [p[0] - target[0], p[2] - target[2]]

    x0 = [math.log(max(start[0], 0.1)), math.log(max(start[1], 0.1))]
    res = least_squares(resid, x0, bounds=([-3, -3], [2, 2]))
    return math.exp(res.x[0]), math.exp(res.x[1])
