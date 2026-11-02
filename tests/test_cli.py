"""The CLI turns each outcome into the right exit code, without calling the real agent."""

import json
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ResultMessage

import opsagent.__main__ as cli
from opsagent.alert import Alert
from opsagent.utils.transcript import TranscriptWriter

ALERT = Path(__file__).resolve().parent.parent / "alerts" / "blocking-orders.json"


def fake_result(subtype: str, *, is_error: bool = False, text: str | None = None) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="test-session",
        total_cost_usd=0.0,
        result=text,
    )


def use_fake_run(monkeypatch: pytest.MonkeyPatch, result: ResultMessage) -> None:
    """Replace the real agent run with one that writes one message and returns `result`."""

    async def fake_run(alert: Alert, transcript: TranscriptWriter) -> ResultMessage:
        transcript.write_message(result)
        return result

    monkeypatch.setattr(cli, "run_diagnosis", fake_run)


def run(tmp_path: Path, *extra: str) -> int:
    return cli.main(["diagnose", "--alert", str(ALERT), "--runs-dir", str(tmp_path), *extra])


def test_invalid_alert_exits_2_before_any_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"signal": "cpu"}', encoding="utf-8")
    exit_code = cli.main(["diagnose", "--alert", str(bad), "--runs-dir", str(tmp_path)])

    assert exit_code == cli.EXIT_INVALID_ALERT
    assert "signal" in capsys.readouterr().err
    assert not (tmp_path / "blk-2026-10-31-0001").exists()  # no transcript: no run started


def test_successful_run_exits_0_and_prints_the_diagnosis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    use_fake_run(monkeypatch, fake_result("success", text="Summary: blocking found"))

    assert run(tmp_path) == cli.EXIT_OK
    assert "Summary: blocking found" in capsys.readouterr().out


@pytest.mark.parametrize("subtype", ["error_max_turns", "error_max_budget_usd", "error_during_execution"])
def test_capped_or_failed_run_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subtype: str) -> None:
    use_fake_run(monkeypatch, fake_result(subtype, is_error=True))

    assert run(tmp_path) == cli.EXIT_RUN_FAILED


def test_success_subtype_with_api_error_exits_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_run(monkeypatch, fake_result("success", is_error=True))

    assert run(tmp_path) == cli.EXIT_RUN_FAILED


def test_missing_api_key_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert run(tmp_path) == cli.EXIT_CONFIGURATION


def test_transcript_is_one_json_object_per_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    use_fake_run(monkeypatch, fake_result("success", text="done"))
    run(tmp_path)

    lines = (tmp_path / "blk-2026-10-31-0001" / "transcript.jsonl").read_text(encoding="utf-8").splitlines()
    records: list[dict[str, Any]] = [json.loads(line) for line in lines]
    assert records[-1]["type"] == "ResultMessage"
    assert records[-1]["subtype"] == "success"
    assert all("recorded_at" in record for record in records)
