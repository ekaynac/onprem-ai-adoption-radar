# On-Prem AI Adoption Radar

A laptop-runnable radar for deciding which AI agent and tooling technologies are worth trying, watching, demoing, or avoiding.

This is not a generic AI news digest. Tools like Horizon and agents-radar already do broad collection and summarization well. This project focuses on agent/tooling adoption judgment for on-prem and enterprise AI workflows.

## V1 Scope

- Coding agents
- General-purpose agents
- MCP and tool servers
- Sandbox and governance tools
- Agent frameworks

## Quick Start

```bash
uv sync --extra dev
uv run radar init
uv run radar scan --days 2
uv run radar report
uv run radar serve
```

The dashboard runs at `http://127.0.0.1:8765`.

## Safety

The radar observes public sources and generates decision cards. It does not install, execute, or operate third-party agents.

## Outputs

Each scan creates inspectable artifacts under:

```txt
data/runs/<run_id>/
  meta.json
  raw_signals.json
  scored_signals.json
  filtered_signals.json
  decision_cards.json
  report.md
```
