"""Persistent user settings stored as JSON next to the application."""

import json
import os

_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

_DEFAULTS = {
    "status_poll_interval": 5000,
    "server_port": 3421,
}

_BOUNDS = {
    "status_poll_interval": (0, 600_000),
    "server_port": (1, 65_535),
}


def _validated(data: dict) -> dict:
    settings = dict(_DEFAULTS)
    if not isinstance(data, dict):
        return settings
    for key, default in _DEFAULTS.items():
        value = data.get(key, default)
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        low, high = _BOUNDS[key]
        if low <= value <= high:
            settings[key] = value
    return settings


def load() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return _validated(data)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def save(data: dict) -> None:
    payload = _validated(data)
    tmp_path = f"{_SETTINGS_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, _SETTINGS_PATH)
