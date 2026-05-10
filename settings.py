"""Persistent user settings stored as JSON next to the application."""

import json
import os

_SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

DEFAULT_SERVER_PORT = 3421

_DEFAULTS = {
    "status_poll_interval": 5000,
    "server_port": DEFAULT_SERVER_PORT,
}

_LEGACY_DEFAULTS = {
    "server_port": 3000,
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
        if value == _LEGACY_DEFAULTS.get(key):
            continue
        low, high = _BOUNDS[key]
        if low <= value <= high:
            settings[key] = value
    return settings


def _needs_rewrite(data: object, payload: dict) -> bool:
    if not isinstance(data, dict):
        return True
    return any(data.get(key) != value for key, value in payload.items())


def _write(payload: dict) -> None:
    tmp_path = f"{_SETTINGS_PATH}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, _SETTINGS_PATH)


def load() -> dict:
    try:
        with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        payload = _validated(data)
        if _needs_rewrite(data, payload):
            try:
                _write(payload)
            except OSError:
                pass
        return payload
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return dict(_DEFAULTS)


def save(data: dict) -> None:
    _write(_validated(data))
