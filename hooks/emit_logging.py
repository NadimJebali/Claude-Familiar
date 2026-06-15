"""Phase 0 logging emitter.

Invoked by Claude Code hooks. Reads the event name from argv[1] and the hook
payload as JSON on stdin, then appends one line to the hook log so we can confirm
the exact payload schema before building the real emit.py.

Design rules (same as the real emitter):
- Must be fast and side-effect-light.
- Must ALWAYS exit 0 and never raise — a hook that errors can disrupt Claude.
"""
import sys
import json
import time
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "mascot" / "hook-log.jsonl"


def main() -> None:
    event = sys.argv[1] if len(sys.argv) > 1 else "UNKNOWN"

    raw = ""
    payload = None
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else None
    except Exception:
        # Keep the raw text if it wasn't valid JSON; never fail.
        payload = None

    record = {
        "ts": time.time(),
        "event": event,
        "payload": payload,
        "raw": None if payload is not None else raw,
    }

    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        # Swallow everything; logging must never break the session.
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
