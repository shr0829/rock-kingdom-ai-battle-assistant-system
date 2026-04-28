from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator


class AnalysisTimingLog:
    """Append-only JSONL timing log for one screenshot analysis run.

    Each event is flushed immediately so a partial log is still useful if a
    model request, capture command, or downstream parsing step fails.
    """

    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.run_id = datetime.now().strftime("%Y%m%d-%H%M%S") + f"-{uuid.uuid4().hex[:8]}"
        self.started_at_perf = time.perf_counter()
        self.path = self.log_dir / f"analysis-{self.run_id}.jsonl"
        self.events: list[dict[str, Any]] = []
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.write_event("run_start")

    @contextmanager
    def step(self, name: str, **metadata: Any) -> Iterator[None]:
        started_at = time.perf_counter()
        try:
            yield
        except Exception as exc:
            self.write_event(
                "step",
                step=name,
                status="error",
                duration_ms=self._elapsed_ms(started_at),
                error_type=type(exc).__name__,
                error=str(exc),
                **metadata,
            )
            raise
        else:
            self.write_event(
                "step",
                step=name,
                status="ok",
                duration_ms=self._elapsed_ms(started_at),
                **metadata,
            )

    def finish(self, status: str, **metadata: Any) -> None:
        self.write_event(
            "run_finish",
            status=status,
            duration_ms=self._elapsed_ms(self.started_at_perf),
            **metadata,
        )

    def write_event(self, event: str, **payload: Any) -> None:
        record = {
            "event": event,
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            **self._json_safe(payload),
        }
        self.events.append(record)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    @staticmethod
    def _elapsed_ms(started_at: float) -> float:
        return round((time.perf_counter() - started_at) * 1000, 3)

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str | int | float | bool) or value is None:
            return value
        return str(value)
