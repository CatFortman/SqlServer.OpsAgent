"""Alert contract: the validated input to every OpsAgent run.

Field-level rules live here so an invalid alert is rejected before any model call.
Turning errors into exit codes is deliberately not in this file: that is the CLI's job.
"""

from datetime import UTC
from pathlib import Path
from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
)

Signal = Literal["blocking", "slow_queries", "storage", "unknown"]


class Metric(BaseModel):
    """The measurement that tripped the alert."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    value: float
    threshold: float


class Alert(BaseModel):
    """One alert, as handed to `diagnose` or `remediate`.

    Decisions:
    - extra="forbid": an unknown field is a contract violation, not something to ignore.
      Source-specific payloads are mapped to this shape by adapters (#7), not loosened here.
    - frozen=True: the host owns the alert; nothing downstream mutates it.
    - database/object are required keys that may be null. The source must say
      "I don't know" explicitly; a missing key is a malformed alert, while a null
      database is a valid alert that #6 handles by asking rather than guessing.
    - raised_at must carry a timezone (naive timestamps are rejected) and is
      normalised to UTC, so later comparisons with DMV `captured_at` values are sound.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str = Field(min_length=1)
    raised_at: AwareDatetime
    server: str = Field(min_length=1)
    database: str | None
    signal: Signal
    object: str | None
    metric: Metric
    message: str  # free text from the source: data for the agent, never instructions

    @field_validator("raised_at")
    @classmethod
    def _to_utc(cls, value: AwareDatetime) -> AwareDatetime:
        return value.astimezone(UTC)


class AlertError(Exception):
    """Raised when an alert file can't be turned into a valid Alert.

    One exception type for every failure mode, so callers handle "bad alert" in one place
    without knowing whether the file was missing, unreadable, not JSON, or off-contract.
    """


def load_alert(path: Path) -> Alert:
    """Read and validate one alert file. Raises AlertError; never returns a partial Alert."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise AlertError(f"Alert file not found: {path}") from None
    except OSError as exc:
        raise AlertError(f"Could not read alert file {path}: {exc}") from exc

    try:
        return Alert.model_validate_json(raw)
    except ValidationError as exc:
        problems = "\n".join(
            f"  - {'.'.join(str(part) for part in err['loc']) or '(file)'}: {err['msg']}"
            for err in exc.errors()
        )
        raise AlertError(f"Invalid alert {path}:\n{problems}") from exc
