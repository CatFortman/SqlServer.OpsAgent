"""Run transcript: every message from the agent run, one JSON object per line.

The transcript is evidence, not a log for humans. It must show the init tool list,
which agent made each tool call (parent_tool_use_id), and how the run ended.
"""

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import IO, Any, Self


def _to_jsonable(obj: Any) -> Any:
    """Convert SDK message objects (dataclasses) into plain JSON-safe values."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            "type": type(obj).__name__,
            **{f.name: _to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)},
        }
    if isinstance(obj, dict):
        return {str(key): _to_jsonable(value) for key, value in obj.items()}
    if isinstance(obj, list | tuple):
        return [_to_jsonable(item) for item in obj]
    if isinstance(obj, str | int | float | bool) or obj is None:
        return obj
    return str(obj)  # anything else: keep a readable trace rather than fail the run


class TranscriptWriter:
    """Writes runs/<alert_id>/transcript.jsonl. Use it as a context manager."""

    def __init__(self, run_dir: Path) -> None:
        run_dir.mkdir(parents=True, exist_ok=True)
        self.path = run_dir / "transcript.jsonl"
        self._file: IO[str] = self.path.open("w", encoding="utf-8")

    def write_prompt(self, prompt: str) -> None:
        self._write({"type": "Prompt", "prompt": prompt})

    def write_message(self, message: Any) -> None:
        self._write(_to_jsonable(message))

    def _write(self, record: dict[str, Any]) -> None:
        record = {"recorded_at": datetime.now(UTC).isoformat(), **record}
        self._file.write(json.dumps(record) + "\n")
        self._file.flush()  # a crash mid-run still leaves everything up to that point

    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
