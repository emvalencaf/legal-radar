"""Canonical wide-event log: one JSONL line per model call, the only source of usage."""

import json
from datetime import UTC, datetime
from pathlib import Path


class WideEventLog:
    def __init__(self, path: Path | str, log_full_content: bool = False):
        self.path = Path(path)
        self.log_full_content = log_full_content

    def emit(self, event: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def usage_today(self, provider: str, model: str, now: datetime | None = None) -> int:
        """Count today's (UTC) successful calls for a provider+model by scanning the log."""
        today = (now or datetime.now(UTC)).astimezone(UTC).date().isoformat()
        if not self.path.exists():
            return 0
        count = 0
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    event = json.loads(line)
                except ValueError:
                    continue  # a torn line must not break routing
                if (
                    event.get("outcome") == "success"
                    and event.get("provider") == provider
                    and event.get("model") == model
                    and str(event.get("timestamp", "")).startswith(today)
                ):
                    count += 1
        return count
