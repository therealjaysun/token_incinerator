# Token Incinerator

A background CLI tool that burns Claude tokens to maintain AI adoption KPIs. It reads your codebase, generates contextually plausible (but unproductive) requests, and fires them at the Claude Code CLI with statistically obfuscated timing — like a mouse jiggler, but for token usage dashboards.

## How it works

1. Walks your target repo and weights files by size and type
2. Generates high-burn prompts (code review, security audit, refactor plan, architecture analysis, doc generation) that reference real file paths so Claude reads them
3. Paces requests using a Poisson process to mimic organic developer behavior
4. All requests use `--allowedTools Read,Grep,Glob` — Claude can't write files or commit anything
5. Runs detached in the background; tracks spend in `~/.incinerator/`

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

### Start

```bash
incinerator start --repo /path/to/your/repo [options]
```

**Options:**

| Flag | Description | Default |
|---|---|---|
| `--repo PATH` | Target repository to read for context (required) | — |
| `--tokens N` | Stop after burning N tokens | — |
| `--usd N` | Stop after spending $N | — |
| `--duration 2h` | Stop after a time duration (`2h`, `30m`, `3600s`) | — |
| `--rate N` | Target tokens/hour, controls inter-request pacing | `5000` |
| `--model MODEL` | Claude model to use | `claude-sonnet-4-5` |
| `--working-hours-only` | Only burn during 9am–5pm local time | off |

Any combination of `--tokens`, `--usd`, and `--duration` can be set — the incinerator stops when the **first** limit is reached. With no budget flags it runs indefinitely until stopped manually.

**Examples:**

```bash
# Burn $10 against your project at a natural pace
incinerator start --repo ~/my-project --usd 10.00

# Burn 500k tokens over at most 4 hours
incinerator start --repo ~/my-project --tokens 500000 --duration 4h

# Aggressive rate, multiple limits
incinerator start --repo ~/my-project --usd 5.00 --tokens 200000 --rate 15000

# Only active during work hours
incinerator start --repo ~/my-project --usd 20.00 --working-hours-only
```

### Status

```bash
incinerator status
```

```
Status: RUNNING (PID 48291)
Repo:   /Users/you/my-project
Model:  claude-sonnet-4-5
Rate:   5,000 tokens/hr

Spend so far:
  Tokens:  12,400
  Cost:    $0.2341
  Runs:    8
  Last:    14:23:07
```

### Stop

```bash
incinerator stop
```

Sends SIGTERM to the background process. State is saved before exit.

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

The incinerator rotates through five prompt types, each designed to maximize token consumption:

| Category | What it asks Claude to do |
|---|---|
| `review` | Full senior-engineer code review — bugs, architecture, performance, all issues cited by file/line |
| `refactor` | Complete refactor plan with new module structure, rewritten files, and risk assessment |
| `security_audit` | Threat model, CWE-classified vulnerabilities, CVSS scores, remediation code |
| `doc_generation` | Architecture diagrams, full API reference, developer guide, troubleshooting guide |
| `architecture` | Current vs. target architecture, anti-pattern identification, ADRs, migration tickets |

Each prompt embeds real file paths from your repo so Claude reads them, burning input context tokens. All prompts end with an instruction to plan only and not write or execute anything.

## Timing

Inter-request delays follow an exponential distribution (Poisson process) with mean `3,600,000ms / rate`. At the default rate of 5,000 tokens/hour, the mean delay between requests is about 12 minutes. Requests naturally cluster and space out, matching the statistical signature of a developer working through a task.

## State files

All state lives in `~/.incinerator/`:

| File | Contents |
|---|---|
| `incinerator.pid` | PID of the running daemon |
| `incinerator_config.json` | Active configuration |
| `state.json` | Cumulative token/cost/run counts |
| `incinerator.log` | JSON-lines event log |

## Auth errors

Before forking the daemon, `incinerator start` runs a preflight check against the Claude CLI. If you're not logged in:

```
Error: Claude is not logged in.
Run 'claude login' to authenticate, then retry.
```

If auth fails mid-session (e.g. token expiry), the daemon logs a `fatal_error` event and shuts down cleanly rather than retrying in a loop.

## Development

```bash
# Install dev dependencies
pip install -e .

# Run tests
pytest

# Run only integration tests
pytest tests/test_integration.py -v
```

104 tests across unit, integration, and daemon lifecycle coverage.
