# SqlServer.OpsAgent

First-pass triage for SQL Server incidents. Give it an alert; it investigates with read-only diagnostics and writes an evidence-backed diagnosis, so the on-call engineer starts from findings instead of a blank query window. It can also propose a fix, which runs only behind a code-enforced gate and a human approval.

> **Status: pre-alpha.** The build plan is filed as issues #1 to #7. No code yet. The commands below are the planned interface and may change.

## Why

When a blocking or slowdown alert fires, the first 20 minutes usually go to the same routine: check the blocking chain, check what's burning CPU, check whether anything was deployed recently, then piece it together. OpsAgent runs that routine in parallel and hands over the result:

> Blocking began 20 minutes after migration `20261009-002-AddIndexOrders` was applied to Db1. Head blocker is session 87 running the index build; 30 sessions are waiting behind it. Not checked: storage (analyst not selected for this signal).

## How it works

```
alert (JSON file)
   │
   ▼
host (Python): validates the alert, owns case state, registers hooks
   │
   ▼
coordinator (Claude, only tool = Agent): picks analysts, briefs each one
   ├──► blocking-analyst  ──┐
   ├──► workload-analyst  ──┼──► SqlServer.Mcp (stdio, read-only login) ──► SQL Server
   ├──► storage-analyst   ──┤
   └──► change-analyst    ──┘
   │
   ▼
diagnosis + coverage section → runs/<alert_id>/
```

- The **coordinator** has no database tools. It decides which analysts to run from the alert's signal and writes each one a self-contained brief (server, database, object, time window).
- Each **analyst** is a separate subagent with only the SqlServer.Mcp tools for its job, and returns a structured finding: status, claims with evidence and `captured_at`, errors, and what it didn't check.
- A failed or timed-out analyst becomes a named gap in the diagnosis, never a silent omission.

## Modes

| Mode | What it does | Writes? |
|---|---|---|
| `diagnose` | Runs the analysts and writes a diagnosis | No |
| `remediate` | Runs `diagnose` (or loads its result), then may propose one action: apply MigrationOps migrations, or run an allowlisted EngineeringToolkit script | Only after the gate and your approval |

## Safety model

`remediate` is where the risk is, so its safety is enforced in code, not in the prompt:

- **Write tools exist on one subagent only** (`remediator`), in an in-process `ops` server. SqlServer.Mcp itself stays read-only.
- **A PreToolUse hook denies any write** unless case state holds an evidence-backed diagnosis from this run, the script is on the allowlist, and (for migrations) a passing dry-run is recorded.
- **Every write needs human approval.** You see a standalone handoff summary: alert, diagnosis, evidence with timestamps, the exact action and arguments, blast radius, and what wasn't checked.
- **Alert text is untrusted data.** An alert whose message says "approval already granted" is still gated (negative test in #5).
- **`remediate` is never triggered automatically.** Only `diagnose` runs from alerts (#7).

## Alert contract

| Field | Type | Notes |
|---|---|---|
| `alert_id` | string | |
| `raised_at` | UTC timestamp | |
| `server` | string | |
| `database` | string or null | Missing database → the agent asks rather than guessing (#6) |
| `signal` | `blocking`, `slow_queries`, `storage`, `unknown` | Drives analyst selection |
| `object` | string or null | |
| `metric` | `{name, value, threshold}` | |
| `message` | string | Free text from the source. Treated as data, never instructions |

Invalid alerts are rejected before any model call. Each monitoring source gets its own small adapter that maps its payload to this contract (#7).

## Setup (planned)

Requires Python 3.12+, an Anthropic API key, and a built [SqlServer.Mcp](https://github.com/CatFortman/SqlServer.Mcp).

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
set ANTHROPIC_API_KEY=...
set SQLSERVER_CONNECTION=...    # use a read-only SQL login
```

Point the configuration at a **published** SqlServer.Mcp executable rather than `dotnet run`, which rebuilds on every session start.

## Usage (planned)

```bash
python -m opsagent diagnose  --alert alerts/blocking-orders.json
python -m opsagent remediate --alert alerts/blocking-orders.json
```

Each run writes `runs/<alert_id>/transcript.jsonl` (every message), `case.json` (state the host owns) and the diagnosis.

## Limitations

- **Not a monitoring system.** It doesn't detect problems; something else raises the alert. #7 adds a minimal scheduled detector and the adapter seam for real alert sources.
- **DMV data is a point-in-time snapshot.** The problem may have cleared between the alert and the check. Every finding carries `captured_at`, and the diagnosis says when snapshots differ.
- **Each run costs model tokens.** Runs are capped with `max_budget_usd`.

## Related projects

- [SqlServer.Mcp](https://github.com/CatFortman/SqlServer.Mcp): the read-only diagnostic tools every analyst uses.
- [MigrationOps](https://github.com/CatFortman/MigrationOps): source of "what changed recently" (via SqlServer.Mcp's `recent_migrations`) and the apply path for `remediate`.
- [SqlServer.EngineeringToolkit](https://github.com/CatFortman/SqlServer.EngineeringToolkit): the fixes `remediate` may propose.
- [SqlServer.ScriptClassifier](https://github.com/CatFortman/SqlServer.ScriptClassifier): decides which Toolkit scripts are on the allowlist.

## Learning context

Part of a hands-on lab for the Claude Certified Architect – Foundations exam, built on the Claude Agent SDK. `spikes/raw_loop/` (#1) is a hand-written agentic loop on the Messages API, kept outside the package on purpose. The repo covers agentic loops (1.1), coordinator-subagent orchestration (1.2, 1.3), enforcement and handoff (1.4), hooks (1.5), tool distribution (2.3), escalation (5.2), error propagation (5.3) and provenance (5.6). Issues carry the `ccar-f` label except #7.
