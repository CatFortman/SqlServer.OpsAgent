"""Host-owned policy enforced in code, not in prompts.

Each hook here is a PreToolUse/PostToolUse callback. The SDK calls it on every matching
tool call, before the permission mode or allow rules are consulted, and a deny from a
hook holds even if the model insists.
"""

from collections.abc import Collection

from claude_agent_sdk import HookCallback, HookContext, HookInput, HookJSONOutput

# The CLI reports the delegation tool as "Task" in the init message and "Agent" in
# tool_use blocks. Match both; the transcript shows which name actually fired.
DELEGATION_TOOL_MATCHER = "Agent|Task"


def make_subagent_allowlist_hook(allowed: Collection[str]) -> HookCallback:
    """Build a PreToolUse hook that denies delegation to any subagent not in `allowed`.

    The bundled Claude Code also registers built-in subagents (general-purpose, Explore,
    Plan, ...). Some of them have Bash and file tools, so without this hook the
    coordinator could reach tools through a subagent even though it has none itself.
    """
    allowed_names = frozenset(allowed)  # snapshot: later changes to the caller's dict can't widen it
    allowed_text = ", ".join(sorted(allowed_names))

    async def deny_unlisted_subagents(
        input_data: HookInput, tool_use_id: str | None, context: HookContext
    ) -> HookJSONOutput:
        if input_data["hook_event_name"] != "PreToolUse":
            return {}

        requested = input_data["tool_input"].get("subagent_type")
        if requested in allowed_names:
            return {}  # no opinion: the normal permission flow continues

        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": (
                    f"Subagent '{requested}' is not available in this run. "
                    f"Delegate only to: {allowed_text}. "
                    "If none of these fits the alert, report that in Coverage instead."
                ),
            }
        }

    return deny_unlisted_subagents
