"""The subagent allowlist is enforced by code, without a model in the loop."""

import asyncio
from typing import Any

import pytest
from claude_agent_sdk import HookJSONOutput, HookMatcher

from opsagent.coordinator import build_options
from opsagent.hooks import DELEGATION_TOOL_MATCHER, make_subagent_allowlist_hook


def delegation(subagent_type: str) -> Any:
    """A PreToolUse input shaped like the one the SDK sends for an Agent call."""
    return {
        "hook_event_name": "PreToolUse",
        "session_id": "test-session",
        "transcript_path": "",
        "cwd": "",
        "tool_name": "Agent",
        "tool_use_id": "toolu_test",
        "tool_input": {
            "subagent_type": subagent_type,
            "description": "test",
            "prompt": "test brief",
        },
    }


def call_hook(subagent_type: str, allowed: set[str]) -> HookJSONOutput:
    hook = make_subagent_allowlist_hook(allowed)
    return asyncio.run(hook(delegation(subagent_type), "toolu_test", {"signal": None}))


def test_allowed_subagent_gets_no_opinion() -> None:
    assert call_hook("blocking-analyst", {"blocking-analyst"}) == {}


@pytest.mark.parametrize("subagent_type", ["general-purpose", "Explore", "Plan", "claude"])
def test_built_in_subagents_are_denied(subagent_type: str) -> None:
    output: Any = call_hook(subagent_type, {"blocking-analyst"})
    decision = output["hookSpecificOutput"]

    assert decision["permissionDecision"] == "deny"
    assert subagent_type in decision["permissionDecisionReason"]  # tells the model what it tried
    assert "blocking-analyst" in decision["permissionDecisionReason"]  # and what it may use


def test_missing_subagent_type_is_denied() -> None:
    output: Any = call_hook("", {"blocking-analyst"})
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_allowlist_is_a_snapshot() -> None:
    allowed = {"blocking-analyst"}
    hook = make_subagent_allowlist_hook(allowed)
    allowed.add("general-purpose")  # mutating the caller's set later must not widen the policy

    output: Any = asyncio.run(hook(delegation("general-purpose"), "toolu_test", {"signal": None}))
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_build_options_wires_the_hook_and_appends_the_schema() -> None:
    options = build_options()

    matchers: list[HookMatcher] = (options.hooks or {})["PreToolUse"]
    assert [m.matcher for m in matchers] == [DELEGATION_TOOL_MATCHER]

    analyst = options.agents["blocking-analyst"] if options.agents else None
    assert analyst is not None
    assert '"$schema"' in analyst.prompt  # the schema is in the prompt, not in a file it can't read
