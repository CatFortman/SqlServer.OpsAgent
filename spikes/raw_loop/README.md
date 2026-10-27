# Raw agentic loop spike

Throwaway spike for #1: a hand-written agentic loop on the Messages API, so the `stop_reason` control flow is something I've debugged rather than read about.

## What the Agent SDK takes over

- **Loop control (`stop_reason`)**: This loop uses `tool_use`, `end_turn` and `max_tokens` to decide when to stop. With the SDK, the loop makes that decision, and the final `ResultMessage` reports the outcome in two fields:
  - `subtype` says why the loop stopped: `success`, `error_max_turns`, `error_max_budget_usd`, `error_during_execution` or `error_max_structured_output_retries`. `result` is only present on `success`.
  - `stop_reason` says why the model stopped on its last turn: `end_turn`, `max_tokens` or `refusal`. It is `null` after a crash.

  `max_tokens` comes from the model: it ran out of output. A turn or budget cap comes from the harness: the host stopped a model that wasn't finished. When a cap cuts the loop off, `stop_reason` is just the last response's value, so if you look only at `stop_reason`, a run cut off by the turn cap can look like a normal finish. In `transcript.jsonl`, the `ResultMessage` `subtype` (`error_max_turns` or `error_max_budget_usd`) tells them apart.

- **Tool execution**: This spike sends a query that produces parallel `tool_use` blocks. After executing the tools, I append the tool results, matched by `tool_use_id`, to the next user message. If a tool raises an error, a readable message goes back to the model with `is_error` set. The SDK runs the whole tool loop and also comes with built-in tools.

- **Permissions**: Whether a tool call is allowed to run (allow, deny, or ask a person). This loop runs every tool Claude asks for, with no check. The SDK runs its checks in a fixed order, and the first one that decides wins:

  hooks → deny rules → ask rules → permission mode → allow rules → `can_use_tool`

  <!-- TODO: name the options that feed each step: permission_mode, allowed_tools / disallowed_tools, can_use_tool. Add the dontAsk-for-diagnose decision and its one-line why. -->

- **Hooks**: This loop has no hooks. Because the SDK owns the loop, it gives you fixed interception points instead: `PreToolUse`, `PostToolUse`, `Stop`. <!-- TODO: one line on why a PreToolUse hook is a stronger guarantee than a prompt instruction -->

- **Context management**: The SDK compacts the conversation automatically as it approaches the context window limit, while this loop raises an error when it reaches the limit.

- **Sessions**: The messages list lives only in memory and is gone when the script exits. The SDK saves sessions and can resume them across runs.

## Anti-patterns avoided

### 1. An iteration cap as the primary stop condition

A cap can terminate the loop before the model has finished, which leaves the task incomplete or wrong. If a task takes 12 turns, a cap of 10 stops the model before it completes the work, and hitting the cap looks the same as a completed run. A cap is still useful as a backstop that stops the loop after an excessive number of turns, logged as abnormal.

### 2. Treating "the assistant produced text" as completion

Text blocks often accompany `tool_use` blocks, so text in a response doesn't mean the task is finished. Treating it as completion skips the follow-up actions the model asked for. `stop_reason` is the signal for completion.

### 3. Parsing the text for "done"

This is brittle. The model can phrase completion differently, or use the word "done" in another context, and the loop draws the wrong conclusion. Processing a keyword block can cause additional blocks that follow the keyword block to stop early. <!-- TODO: sharpen this sentence -->
