"""
Local monthly call-quota guard for the Amadeus production environment.

Amadeus's Flight Offers Search gives 2,000 free calls/month in production,
then bills per call. This tracks calls made this calendar month in a small
local JSON file and refuses further calls once a conservative cap is hit —
default 1,800, leaving headroom for manual testing/debugging calls that
don't go through the collector. Never trust this alone for a shared/multi-
machine setup; it's a single-machine safety net, not a real billing guard.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

_STATE_FILE = Path(__file__).parent / ".amadeus_quota.json"
DEFAULT_MONTHLY_LIMIT = 1800


def _current_month_key() -> str:
    return time.strftime("%Y-%m")


def _load() -> dict:
    if not _STATE_FILE.exists():
        return {}
    try:
        return json.loads(_STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict) -> None:
    _STATE_FILE.write_text(json.dumps(state, indent=2))


class QuotaTracker:
    def __init__(self, monthly_limit: int = DEFAULT_MONTHLY_LIMIT):
        self.monthly_limit = monthly_limit

    def used_this_month(self) -> int:
        return _load().get(_current_month_key(), 0)

    def remaining(self) -> int:
        return max(0, self.monthly_limit - self.used_this_month())

    def can_call(self, n: int = 1) -> bool:
        return self.remaining() >= n

    def record_calls(self, n: int = 1) -> None:
        state = _load()
        key = _current_month_key()
        state[key] = state.get(key, 0) + n
        _save(state)
