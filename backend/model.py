"""Small, secret-free contract shared by the three quota adapters."""
import math
from datetime import datetime, timezone


NAMES = {"codex": "Codex", "antigravity": "Antigravity", "opencode": "OpenCode Go"}


def percent(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return min(100, max(0, float(value))) if math.isfinite(value) else None


def remaining_percent(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return percent((1 - value) * 100) if 0 <= value <= 1 else None


def timestamp(value):
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (float, int)):
            return value if math.isfinite(value) and value > 0 else None
        if isinstance(value, dict):
            return timestamp(float(value.get("seconds", 0)))
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()
    except (AttributeError, ValueError, TypeError, OverflowError):
        return None


def window_label(minutes):
    if minutes == 300:
        return "5 horas"
    if minutes == 10080:
        return "Semanal"
    if minutes == 1440:
        return "Diaria"
    return f"{minutes:g} min" if isinstance(minutes, (float, int)) and minutes > 0 else "Cuota"


def quota(key, label, used=None, reset=None, minutes=None, group=None, disabled=False):
    return {"id": str(key), "label": str(label), "usedPercent": percent(used),
            "resetsAt": timestamp(reset), "windowMinutes": minutes,
            "group": group, "disabled": bool(disabled)}


def result(provider, quotas, resets=None, message=None):
    import time
    if not quotas:
        return {"id": provider, "name": NAMES[provider], "status": "unavailable",
                "message": message or "Cuota no disponible", "updatedAt": None,
                "quotas": [], "resetsAvailable": resets}
    return {"id": provider, "name": NAMES[provider], "status": "ok",
            "message": message, "updatedAt": time.time(), "quotas": quotas,
            "resetsAvailable": resets}


class ProviderError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message
        super().__init__(message)
