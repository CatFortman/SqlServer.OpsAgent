"""The run's guardrails, checked on the options object without starting an agent."""

from pathlib import Path

from claude_agent_sdk import AgentDefinition, ClaudeAgentOptions, HookMatcher

from opsagent.coordinator import (
    CHECK_BLOCKING_TOOL,
    SQLSERVER_SERVER_KEY,
    RunConfig,
    build_options,
)
from opsagent.hooks import DELEGATION_TOOL_MATCHER

CONFIG = RunConfig(
    sqlserver_mcp_path=Path("C:/Tools/SqlServer.Mcp/SqlServer.Mcp.exe"),
    sqlserver_connection="Server=test;Database=Orders",
)


def options() -> ClaudeAgentOptions:
    return build_options(CONFIG)


def analyst() -> AgentDefinition:
    agents = options().agents or {}
    return agents["blocking-analyst"]


def test_coordinator_can_see_only_the_delegation_tool() -> None:
    assert options().tools == ["Agent"]
    assert not options().mcp_servers  # SqlServer.Mcp is never attached to the coordinator


def test_analyst_owns_the_sqlserver_server() -> None:
    servers = analyst().mcpServers or []
    assert len(servers) == 1

    entry = servers[0]
    assert isinstance(entry, dict)
    config = entry[SQLSERVER_SERVER_KEY]
    assert config["command"] == str(CONFIG.sqlserver_mcp_path)
    assert config["env"] == {"SQLSERVER_CONNECTION": CONFIG.sqlserver_connection}


def test_tool_is_available_to_the_analyst_and_approved_for_the_session() -> None:
    assert CHECK_BLOCKING_TOOL == "mcp__sqlserver__check_blocking"
    assert analyst().tools == [CHECK_BLOCKING_TOOL]  # availability
    assert CHECK_BLOCKING_TOOL in options().allowed_tools  # approval


def test_guardrails() -> None:
    opts = options()
    assert opts.permission_mode == "dontAsk"
    assert opts.setting_sources == []
    assert opts.env["CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH"] == "1"
    assert opts.env["CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS"] == "1"


def test_allowlist_hook_is_wired_and_schema_is_in_the_prompt() -> None:
    matchers: list[HookMatcher] = (options().hooks or {})["PreToolUse"]
    assert [m.matcher for m in matchers] == [DELEGATION_TOOL_MATCHER]
    assert '"$schema"' in analyst().prompt  # the schema is in the prompt, not in a file it can't read
