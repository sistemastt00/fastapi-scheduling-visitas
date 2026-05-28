"""
state.py — Estado compartido en memoria con persistencia en disco.
"""
import collections
import json
from pathlib import Path

_STATE_FILE = Path(__file__).parent / "monitor_state.json"

summaries: collections.deque = collections.deque(maxlen=50)
history:   collections.deque = collections.deque(maxlen=100)
stats:     dict[str, int]    = {"scheduled": 0, "rescheduled": 0, "canceled": 0, "errors": 0}


def save() -> None:
    try:
        _STATE_FILE.write_text(
            json.dumps({"summaries": list(summaries), "history": list(history)},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def load() -> None:
    try:
        data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        for s in reversed(data.get("summaries", [])):
            summaries.appendleft(s)
        for h in reversed(data.get("history", [])):
            history.appendleft(h)
    except Exception:
        pass
