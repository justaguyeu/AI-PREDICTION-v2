"""
engine/storage.py
=================
Daily prediction files: data/predictions/predictions_<YYYY-MM-DD>.json, keyed "<home>_vs_<away>".

These files are the record of what was predicted before kickoff (review.py grades them), so:
  - writes are atomic (temp file + rename), so a crash or a concurrent reader never sees half a file;
  - an unreadable file is moved aside, never silently replaced by an empty one;
  - the first prediction stored for a match by an engine version is kept: saving again does not
    overwrite it; a newer engine version stores a fresh one and the old one is kept under
    "<home>_vs_<away>@<old version>";
  - each entry carries the engine version and the time it was made.
"""
import datetime
import json
import os
import threading

from engine.model import MODEL_VERSION

ENGINE_VERSION = MODEL_VERSION   # cached predictions from an older engine are ignored
STORAGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "predictions")
_LOCK = threading.Lock()         # the Flask app serves requests on several threads


def get_storage_path(day: datetime.date | None = None):
    day = day or datetime.date.today()
    return os.path.join(STORAGE_DIR, f"predictions_{day:%Y-%m-%d}.json")


def _read(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        aside = f"{path}.unreadable-{stamp}"
        os.replace(path, aside)
        print(f"  [Storage] {path} could not be read ({e}); moved to {aside} so nothing is lost")
        return {}


def _write(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_all_predictions(day: datetime.date | None = None) -> dict:
    return _read(get_storage_path(day))


def get_prediction(home, away):
    pred = load_all_predictions().get(f"{home}_vs_{away}")
    if pred and pred.get("engine") == ENGINE_VERSION and pred.get("status") == "success":
        return pred
    return None


def save_prediction(home, away, prediction_data) -> dict:
    """Store a prediction unless one from this engine version already exists. Returns the stored entry."""
    key = f"{home}_vs_{away}"
    with _LOCK:
        path = get_storage_path()
        data = _read(path)                      # re-read inside the lock: another writer may have saved
        existing = data.get(key)
        if existing and existing.get("engine") == ENGINE_VERSION:
            return existing
        if existing:                            # older engine: keep its prediction under its own key
            data.setdefault(f"{key}@{existing.get('engine') or 'old'}", existing)
        entry = {**prediction_data, "engine": ENGINE_VERSION,
                 "saved_at": datetime.datetime.now().isoformat(timespec="seconds")}
        data[key] = entry
        _write(path, data)
        return entry
