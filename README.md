# Token Incinerator

<img src="logo.png" alt="Token Incinerator" width="200" />

A background CLI tool that burns Claude tokens to maintain AI adoption KPIs. It samples files from your codebase, builds high-burn prompts, and fires them at the Claude Code CLI — like a mouse jiggler, but for token usage dashboards.

## How it works

1. Walks your target repo and weights files by size and type (common junk dirs pruned).
2. Rotates through five prompt categories (review, refactor, security audit, docs, architecture). Each prompt **embeds file contents** (truncated per file) so Claude answers in one shot — no multi-turn tool reads.
3. Runs **`claude`** with `--output-format json`, **`--max-turns 1`**, and **no tools** (`--allowedTools ""`), so each run is a single completion. Token and cost counts come from the JSON `usage` and `total_cost_usd` fields returned by the CLI.
4. **Default pacing:** back-to-back runs (no artificial delay) — throughput is limited by how fast each completion returns. **`--statistical`** adds Poisson-distributed gaps between runs (~30s mean) to mimic organic activity (fixed internal rate, not configurable).
5. Runs detached in the background; **`incinerator start`** attaches a live **watch** (stats, budget bars, **activity log** tailing `~/.incinerator/incinerator.log`, animated status line).

## Requirements

- Python 3.11+
- [Claude Code CLI](https://claude.ai/code) installed and logged in (`claude login`)

## Install

```bash
pip install -e /path/to/token_incinerator
```

Or from the project directory:

```bash
pip install -e .
```

## Usage

### CLI Help

```bash
incinerator --help
```

**Commands:**

| Command | Purpose | Help |
|---|---|---|
| `start` | Start daemon and attach live watch | `incinerator start --help` |
| `status` | Show daemon/process and spend summary | `incinerator status --help` |
| `stop` | Stop the background daemon | `incinerator stop --help` |
| `watch` | Reconnect to live display | `incinerator watch --help` |

### Start

```bash
incinerator start --repo /path/to/your/repo [options]
```

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--repo PATH` | Target repository (required) | — |
| `--tokens N` | Stop after burning N tokens | — |
| `--usd N` | Stop after spending $N | — |
| `--duration 2h` | Stop after a time budget (`2h`, `30m`, `3600s`) | — |
| `--model MODEL` | Claude model to use | Claude's own default |
| `--working-hours-only` | Only burn during a simulated workday activity window | off |
| `--statistical` | Poisson-distributed delays between runs (natural pacing) | off (full blast) |
| `--help` | Show command help and exit | — |

There is **no `--rate` flag** — default mode runs the next prompt as soon as the previous one finishes.

Any combination of `--tokens`, `--usd`, and `--duration` can be set — the incinerator stops when the **first** limit is reached. With no budget flags it runs until you stop it manually.

**Examples:**

```bash
# Burn $10 against your project (back-to-back runs)
incinerator start --repo ~/my-project --usd 10.00

# Burn up to 500k tokens, stop after 4 hours at the latest
incinerator start --repo ~/my-project --tokens 500000 --duration 4h

# Natural-looking gaps between runs (~30s average between completions)
incinerator start --repo ~/my-project --usd 5.00 --statistical

# Only active during simulated work hours
incinerator start --repo ~/my-project --usd 20.00 --working-hours-only
```

### Status

```bash
incinerator status
```

Example output:

```
Status: RUNNING (PID 48291)
Repo:   /Users/you/my-project
Model:  (claude default)
Mode:   full blast

Spend so far:
  Tokens:  12,400
  Cost:    $0.2341
  Runs:    8
  Last:    14:23:07
```

With `--statistical`, `Mode:` shows `statistical` instead of `full blast`.

### Stop

```bash
incinerator stop
```

Sends SIGTERM to the background process. State is saved before exit.

### Watch

```bash
incinerator watch
```

Reconnects to the same live display as `start` (token/cost stats, budget progress, **Activity Log** with recent daemon events, animated status when running).

### Logs

```bash
tail -f ~/.incinerator/incinerator.log
```

Each line is a JSON object:

```json
{"timestamp": "2026-04-15T14:23:05Z", "event": "prompt_dispatched", "category": "security_audit"}
{"timestamp": "2026-04-15T14:23:09Z", "event": "run_complete", "result": {"success": true, "cost_usd": 0.031, "input_tokens": 3200, "output_tokens": 1100}}
```

## Prompt categories

The incinerator cycles through five categories. Prompts are **short, focused asks** (code review bullets, security findings, refactor notes, etc.) with **embedded file excerpts** (binary extensions and null-byte files skipped). Every prompt ends with a plan-only suffix: no shell commands, no writes, no commits.

| Category | What it asks Claude to do |
|---|---|
| `review` | Top issues per file with line references and fixes |
| `refactor` | SRP violations and concrete refactor suggestions |
| `security_audit` | Vulnerabilities with severity and one-line fixes |
| `doc_generation` | API-style docs for public symbols |
| `architecture` | ASCII diagram, concerns, improvements |

## Timing and modes

| Mode | Behavior |
|---|---|
| **Full blast** (default) | No extra delay between runs — only Claude latency and your budgets cap speed. |
| **`--statistical`** | After each successful run, sleep a random time from an exponential distribution with mean ~**30 seconds** between starts (~120 runs/hour target). |

## State files

All state lives in `~/.incinerator/`:

| File | Contents |
|---|---|
| `incinerator.pid` | PID of the running daemon |
| `incinerator_config.json` | Active configuration |
| `state.json` | Cumulative token/cost/run counts |
| `incinerator.log` | JSON-lines event log (also shown in the watch **Activity Log**) |

## Development

Tests and fixtures live under `tests/` on the **`dev`** branch. **`main`** is shipped without that tree; `.gitignore` lists `tests/` so local checkouts match. Run tests from a `dev` checkout: `pytest`.
