---
name: agentbell-notify
description: Send a local AgentBell desktop notification when a turn ends, a long-running task completes, or the agent needs permission or user input, and never use it to approve or resume work.
---

# agentbell-notify

Send one notification to the AgentBell desktop app running on the same machine.
The helper talks to `http://127.0.0.1:<port>/notify` only, uses the Python
standard library, and never reads or transmits conversation content.

## When to call

- Every turn ends: report `succeeded`, `failed`, or `canceled`.
- A long task (roughly over one minute) completes.
- The agent is blocked waiting for permission, an answer, or other input:
  use `--status running --needs-input --wait-reason permission|question`.
- A turn starts and progress matters: optional `--phase started`.

## Command

```bash
python ~/.agents/skills/agentbell-notify/agentbell_notify.py \
  --title "Build auth service" \
  --status succeeded \
  --summary "All tests passed" \
  --duration 8m30s \
  --session-id "$DSH_SESSION_ID" \
  --dedupe-key "dsh:$DSH_SESSION_ID:3"
```

Waiting for permission:

```bash
python agentbell_notify.py --title "Deploy" --status running \
  --needs-input --wait-reason permission \
  --summary "Waiting for permission to run migrations"
```

## Options

| Option | Meaning |
| --- | --- |
| `--title` | Title, default `未命名任务`, max 200 chars |
| `--status` | `succeeded` (default), `failed`, `canceled`, `running` |
| `--summary` | Short text, max 4000 chars |
| `--duration` | Human-readable elapsed time, e.g. `8m30s` |
| `--session-id` / `--run-id` | Group notifications by session or run |
| `--dedupe-key` | Same key updates the existing notification |
| `--source` | Sender label, default `DeepSeek Harness` |
| `--phase` | `started`, `progress`, `waiting_input`, `resumed`, `finished`, `note` |
| `--needs-input` | Waiting for the user; implies `status=running` |
| `--wait-reason` | `permission`, `question`, `rate_limit`, `context_limit`, `other` |
| `--require-ack` / `--silent` | Require acknowledgement / suppress popups |
| `--progress` | Progress percentage 0-100 |
| `--origin-pid` / `--working-dir` | Enables the "back to terminal" action |
| `--config` / `--url` / `--token` | Override config file, endpoint, or token |
| `--json` | Print the full JSON response instead of the notification id |

## Dedupe and sessions

Use one stable `--session-id` per conversation and a `--dedupe-key` like
`dsh:<session_id>:<turn>` so a repeated report for the same turn updates the
existing card instead of stacking a duplicate. Keep `--run-id` stable for the
whole run (`dsh:<session_id>` in the bundled dsh plugin).

The endpoint and token are discovered from `--config`, `AGENTBELL_CONFIG`,
`AGENTBELL_HOME/config.json`, the platform configuration directories, or
`~/.agentbell/config.json`. `--token` wins over the config file.

## Forbidden

- Do not use this skill to approve permissions, answer prompts, resume turns,
  or control the agent in any way.
- Do not fabricate `--source`, `--session-id`, or `--run-id`.
- Do not print, log, or embed the token in arguments shown to the user.
- Do not send conversation transcripts, secrets, or file contents as `--summary`.
- Do not run shell commands through this tool; it only sends one HTTP request.
