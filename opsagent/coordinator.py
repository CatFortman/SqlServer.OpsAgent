"""Coordinator for `diagnose`: builds the agent options and runs one alert through them.

The coordinator delegates; only the blocking analyst can reach SQL Server, through its
own SqlServer.Mcp process. Everything the run may do is defined here in code.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

# The key we register SqlServer.Mcp under. It becomes the middle part of every tool name:
# mcp__<server key>__<tool name>. Define each full name once and reuse it, because it must
# match in two places (the analyst's `tools` and the session's `allowed_tools`).
SQLSERVER_SERVER_KEY = "sqlserver"
CHECK_BLOCKING_TOOL = f"mcp__{SQLSERVER_SERVER_KEY}__check_blocking"


class ConfigurationError(Exception):
    """The run can't start because the environment is missing something."""


class AgentRunError(Exception):
    """The agent run failed before it produced a result message."""


@dataclass(frozen=True)
class RunConfig:
    """Settings read from the environment once, before any model call."""

    sqlserver_mcp_path: Path
    sqlserver_connection: str


def load_config() -> RunConfig:
    """Read and check the environment. Fails before a single token is spent."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ConfigurationError("ANTHROPIC_API_KEY is not set.")

    mcp_path = os.environ.get("SQLSERVER_MCP_PATH")
    if not mcp_path:
        raise ConfigurationError("SQLSERVER_MCP_PATH is not set (path to the published SqlServer.Mcp.exe).")
    if not Path(mcp_path).is_file():
        raise ConfigurationError(f"SQLSERVER_MCP_PATH does not point to a file: {mcp_path}")

    connection = os.environ.get("SQLSERVER_CONNECTION")
    if not connection:
        raise ConfigurationError("SQLSERVER_CONNECTION is not set.")

    return RunConfig(sqlserver_mcp_path=Path(mcp_path), sqlserver_connection=connection)


def load_prompt(relative_path: str) -> str:
    """Read one prompt file from opsagent/agents/."""
    return (PROMPTS_DIR / relative_path).read_text(encoding="utf-8").strip()


def sqlserver_mcp_server(config: RunConfig) -> dict[str, Any]:
    """Inline stdio config for SqlServer.Mcp: {server key: how to start the process}.

    The SDK starts this exe as a child process when the analyst first needs it, talks
    to it over stdin/stdout, and stops it at the end of the run. The child gets its
    connection string from `env`: OpsAgent is the launcher, so OpsAgent passes it in.
    """
    return {
        SQLSERVER_SERVER_KEY: {
            "type": "stdio",
            "command": str(config.sqlserver_mcp_path),
            "args": [],
            "env": {"SQLSERVER_CONNECTION": config.sqlserver_connection},
        }
    }


def build_options(config: RunConfig) -> ClaudeAgentOptions:
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
            tools=[CHECK_BLOCKING_TOOL],  # AVAILABILITY: the only tool this analyst can see
            mcpServers=[sqlserver_mcp_server(config)],  # the server exists for this analyst only
            model=MODEL,
        ),
    }

    return ClaudeAgentOptions(
        system_prompt=load_prompt("coordinator/coordinator.md"),
        tools=["Agent"],  # AVAILABILITY: the coordinator sees only the delegation tool
        allowed_tools=[
            "Agent",
            CHECK_BLOCKING_TOOL,  # APPROVAL: lets the analyst's call pass step 5 in dontAsk
        ],
        permission_mode="dontAsk",  # anything not approved above is denied, never prompted
        setting_sources=[],  # ignore ~/.claude and any project .claude/
        agents=analysts,
        model=MODEL,
        max_budget_usd=MAX_BUDGET_USD,
        env={
            "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "1",  # analysts can't spawn their own subagents
            "CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS": "1",  # remove general-purpose and friends
        },
        hooks={
            "PreToolUse": [
                HookMatcher(
                    matcher=DELEGATION_TOOL_MATCHER,
                    hooks=[make_subagent_allowlist_hook(analysts.keys())],  # allowlist = analyst names
                )
            ]
        },
    )


async def run_diagnosis(alert: Alert, transcript: TranscriptWriter) -> ResultMessage:
    """Run the coordinator on one alert. Every message goes to the transcript.

    Returns the final ResultMessage whatever its subtype; the caller decides what a
    non-success result means. Raises ConfigurationError before any model call if the
    environment is incomplete, and AgentRunError if the run ends without a result.
    """
    config = load_config()
    options = build_options(config)

    prompt = alert.model_dump_json(indent=2)
    transcript.write_prompt(prompt)

    result: ResultMessage | None = None
    try:
        async for message in query(prompt=prompt, options=options):
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
