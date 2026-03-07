import json
import os
import datetime

def get_storage_path():
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    return f"predictions_{today}.json"

def load_all_predictions():
    path = get_storage_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_all_predictions(data):
    path = get_storage_path()
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def get_prediction(home, away):
    data = load_all_predictions()
    key = f"{home}_vs_{away}"
    return data.get(key)

def save_prediction(home, away, prediction_data):
    data = load_all_predictions()
    key = f"{home}_vs_{away}"
    data[key] = prediction_data
    save_all_predictions(data)
