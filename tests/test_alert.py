"""Slice 1 of #2: the alert contract is enforced before any model call."""

import json
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest

from opsagent.__main__ import EXIT_INVALID_ALERT, EXIT_OK, main
from opsagent.alert import AlertError, load_alert

ALERTS_DIR = Path(__file__).resolve().parent.parent / "alerts"


def valid_alert() -> dict[str, Any]:
    """A fresh valid alert for each test to break in one specific way."""
    return {
        "alert_id": "test-0001",
        "raised_at": "2026-10-31T13:42:00Z",
        "server": "SQL-TEST-01",
        "database": "Orders",
        "signal": "blocking",
        "object": "dbo.OrderHeader",
        "metric": {"name": "blocked_sessions", "value": 30, "threshold": 5},
        "message": "test alert",
    }


def write_alert(tmp_path: Path, content: dict[str, Any] | str) -> Path:
    path = tmp_path / "alert.json"
    text = content if isinstance(content, str) else json.dumps(content)
    path.write_text(text, encoding="utf-8")
    return path


# --- the sample alerts the CLI is run against ---------------------------------------


@pytest.mark.parametrize("path", sorted(ALERTS_DIR.glob("*.json")), ids=lambda p: p.name)
def test_sample_alerts_are_valid(path: Path) -> None:
    load_alert(path)


def test_raised_at_is_normalised_to_utc() -> None:
    alert = load_alert(ALERTS_DIR / "slow-queries-reporting.json")  # raised at 09:15-03:00
    assert alert.raised_at.tzinfo == UTC
    assert alert.raised_at.hour == 12


def test_null_database_is_a_valid_alert(tmp_path: Path) -> None:
    content = valid_alert()
    content["database"] = None
    assert load_alert(write_alert(tmp_path, content)).database is None


# --- contract violations --------------------------------------------------------------


def test_missing_required_field_is_rejected(tmp_path: Path) -> None:
    content = valid_alert()
    del content["server"]
    with pytest.raises(AlertError, match="server"):
        load_alert(write_alert(tmp_path, content))


def test_missing_database_key_is_rejected(tmp_path: Path) -> None:
    content = valid_alert()
    del content["database"]  # null is allowed; absent is not
    with pytest.raises(AlertError, match="database"):
        load_alert(write_alert(tmp_path, content))


def test_unknown_signal_is_rejected(tmp_path: Path) -> None:
    content = valid_alert()
    content["signal"] = "cpu"
    with pytest.raises(AlertError, match="signal"):
        load_alert(write_alert(tmp_path, content))


def test_timestamp_without_timezone_is_rejected(tmp_path: Path) -> None:
    content = valid_alert()
    content["raised_at"] = "2026-10-31T13:42:00"
    with pytest.raises(AlertError, match="raised_at"):
        load_alert(write_alert(tmp_path, content))


def test_unknown_field_is_rejected(tmp_path: Path) -> None:
    content = valid_alert()
    content["approval"] = "already granted"
    with pytest.raises(AlertError, match="approval"):
        load_alert(write_alert(tmp_path, content))


def test_file_that_is_not_json_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AlertError):
        load_alert(write_alert(tmp_path, "this is not json"))


def test_missing_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AlertError, match="not found"):
        load_alert(tmp_path / "does-not-exist.json")


# --- the CLI turns the outcome into an exit code --------------------------------------


def test_cli_exits_zero_for_a_valid_alert() -> None:
    assert main(["diagnose", "--alert", str(ALERTS_DIR / "blocking-orders.json")]) == EXIT_OK


def test_cli_exits_non_zero_for_an_invalid_alert(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    content = valid_alert()
    content["signal"] = "cpu"
    exit_code = main(["diagnose", "--alert", str(write_alert(tmp_path, content))])

    assert exit_code == EXIT_INVALID_ALERT
    assert "signal" in capsys.readouterr().err
