"""Coordinator for `diagnose`: builds the agent options and runs one alert through them.

Slice 2 of #2: the coordinator delegates to one analyst that has no tools yet, so the
first runs test delegation and the transcript only. SqlServer.Mcp is attached in a later step.
"""

import os
from pathlib import Path

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ClaudeSDKError,
    HookMatcher,
    ResultMessage,
    query,
)

from opsagent.alert import Alert
from opsagent.hooks import DELEGATION_TOOL_MATCHER, make_subagent_allowlist_hook
from opsagent.utils.transcript import TranscriptWriter

# Prompt files ship inside the package, so resolve them from this file, not the cwd.
PROMPTS_DIR = Path(__file__).parent / "agents"

MODEL = "haiku"
MAX_BUDGET_USD = 0.50


class ConfigurationError(Exception):
    """The run can't start because the environment is missing something."""


class AgentRunError(Exception):
    """The agent run failed before it produced a result message."""


def load_prompt(relative_path: str) -> str:
    """Read one prompt file from opsagent/agents/."""
    return (PROMPTS_DIR / relative_path).read_text(encoding="utf-8").strip()


def build_options() -> ClaudeAgentOptions:
    """Everything the run is allowed to do, defined in code (no settings files)."""
    analyst_prompt = load_prompt("blocking_analyst/blocking_analyst.md")
    analyst_schema = load_prompt("blocking_analyst/schema.json")
    blocking_analyst_prompt = f"{analyst_prompt}\n\n```json\n{analyst_schema}\n```"

    analysts = {
        "blocking-analyst": AgentDefinition(
            background=False,
            description=(
                "Investigates SQL Server blocking: blocking chains, head blockers, "
                "lock waits and blocked sessions, using read-only diagnostics. "
                "Use for alerts with signal 'blocking'. Does not analyse query "
                "performance or storage, and never proposes or runs fixes."
            ),
            prompt=blocking_analyst_prompt,
            tools=[],  # none yet: slice 2 tests delegation only. SqlServer.Mcp comes next.
            model=MODEL,
        ),
    }

    return ClaudeAgentOptions(
        system_prompt=load_prompt("coordinator/coordinator.md"),
        tools=["Agent"],  # the only tool the coordinator can see
        allowed_tools=["Agent"],  # auto-approve it
        permission_mode="dontAsk",  # anything else that would prompt is denied
        setting_sources=[],  # ignore ~/.claude and any project .claude/
        agents=analysts,
        model=MODEL,
        max_budget_usd=MAX_BUDGET_USD,
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher=DELEGATION_TOOL_MATCHER,
                    hooks=[make_subagent_allowlist_hook(analysts)],  # allowlist = the analysts defined above
                )
            ]
        },
    )


async def run_diagnosis(alert: Alert, transcript: TranscriptWriter) -> ResultMessage:
    """Run the coordinator on one alert. Every message goes to the transcript.

    Returns the final ResultMessage whatever its subtype; the caller decides what a
    non-success result means. Raises AgentRunError if the run ends without one.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ConfigurationError("ANTHROPIC_API_KEY is not set.")

    prompt = alert.model_dump_json(indent=2)
    transcript.write_prompt(prompt)

    result: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=build_options()):
            transcript.write_message(message)
            if isinstance(message, ResultMessage):
                result = message
    except ClaudeSDKError as exc:
        # query() raises after yielding an error result. If we already have the
        # result, it carries the reason; only a run with no result is a crash.
        if result is None:
            raise AgentRunError(str(exc)) from exc

    if result is None:
        raise AgentRunError("The run ended without a result message.")
    return result
