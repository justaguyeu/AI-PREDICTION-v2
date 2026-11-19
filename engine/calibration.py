"""
engine/calibration.py
=====================
Maps a market's raw probability to the hit rate that picks with that
probability actually achieved in review.py's walk-forward simulation:
"the model says 58%" -> "picks like this won 54% of the time".

Built per market from (prob, hit) pairs: equal-count bins, each bin's hit rate
shrunk toward its mean probability (small bins move little), then forced to be
non-decreasing. Stored in engine/calibration.json (rebuild with
`python review.py --start 2025-08-01 --refit weekly --calibrate`).
"""
import json
import os

import numpy as np

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibration.json")
SHRINK = 50          # pseudo-observations pulling each bin toward the raw probability
MIN_BIN = 150
_CACHE: dict | None = None


def _pav(y, w):
    """Pool-adjacent-violators: weighted non-decreasing fit."""
    blocks = [[yi, wi, 1] for yi, wi in zip(y, w)]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] > blocks[i + 1][0]:
            y0, w0, n0 = blocks[i]
            y1, w1, n1 = blocks.pop(i + 1)
            blocks[i] = [(y0 * w0 + y1 * w1) / (w0 + w1), w0 + w1, n0 + n1]
            i = max(i - 1, 0)
        else:
            i += 1
    return [b[0] for b in blocks for _ in range(b[2])]


def build(graded) -> dict:
    """graded: DataFrame with columns market, prob, hit."""
    out = {}
    for market, sub in graded.groupby("market"):
        sub = sub.sort_values("prob")
        n = len(sub)
        if n < 2 * MIN_BIN:
            continue
        nbins = max(2, min(15, n // MIN_BIN))
        xs, ys, ws = [], [], []
        for chunk in np.array_split(np.arange(n), nbins):
            p = sub["prob"].to_numpy()[chunk]
            h = sub["hit"].to_numpy()[chunk].astype(float)
            xs.append(float(p.mean()))
            ys.append(float((h.sum() + SHRINK * p.mean()) / (len(h) + SHRINK)))
            ws.append(len(h))
        ys = _pav(ys, ws)
        out[market] = {"x": [round(v, 4) for v in xs], "y": [round(v, 4) for v in ys], "n": n}
    return out


def save(cal: dict, meta: dict | None = None) -> str:
    with open(PATH, "w", encoding="utf-8") as f:
        json.dump({"meta": meta or {}, "markets": cal}, f, indent=1)
    global _CACHE
    _CACHE = None
    return PATH


def meta() -> dict:
    """What the calibration was built from (matches, date range)."""
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f).get("meta", {})
    except (OSError, ValueError):
        return {}


def _load() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _CACHE = json.load(f).get("markets", {})
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def hit_rate(market: str, prob: float) -> float:
    """Calibrated probability that a pick with raw probability `prob` wins (prob itself if uncalibrated)."""
    c = _load().get(market)
    if not c:
        return prob
    x = [0.0] + c["x"] + [1.0]
    y = [0.0] + c["y"] + [1.0]
    return float(np.interp(prob, x, y))
