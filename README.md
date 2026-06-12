# On-Prem AI Adoption Radar

**A self-hosted, deterministic radar that decides which AI agent & tooling technologies are worth _adopting_, _piloting_, _watching_, or _avoiding_ for on-prem and enterprise workflows.**

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Tests](https://img.shields.io/badge/tests-168%20passing-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-%E2%89%A580%25%20enforced-brightgreen)
![Core](https://img.shields.io/badge/core-deterministic%20·%20no%20LLM%20required-blueviolet)
![License](https://img.shields.io/badge/license-Unlicense%20(public%20domain)-lightgrey)

This is **not** a generic AI news digest. It collects real signals (GitHub releases, registries, vendor/engineering blogs), scores them against an on-prem adoption rubric, and produces **decision cards** with rings — plus a cumulative timeline of how each project moves over time. It runs on a laptop, needs no cloud service, and the entire scoring pipeline is **deterministic** (an LLM is optional and off by default).

---

## Why

Most "AI radar" tools summarize news. This one makes a *decision*: given a tool, should you adopt it now, pilot it, keep watching, or avoid it — specifically through an **on-prem / enterprise** lens (local runnability, data exposure, sandbox posture, deployment complexity, license risk, enterprise integration). Decisions are reproducible because they come from deterministic scoring, not a prompt.

## Highlights

- 🧭 **Decision rings** — `adopt` / `pilot` / `watch` / `avoid`, from a deterministic 7-dimension score + on-prem rubric.
- ⚖️ **Hybrid ring calibration** — absolute gates (security/excellence) plus a quartile-aware, size-capped promotion so rings actually discriminate and "Try This Week" stays a short, high-conviction list.
- 📡 **Firehose classification** — broad vendor blogs (NVIDIA, HuggingFace, Ollama, Red Hat) are re-attributed entry-by-entry to the projects they mention, instead of flooding the radar. Deterministic matching with an **optional, off-by-default LLM** second pass for the ambiguous tail.
- 🆕 **Delta / "Try This Week"** — a separate report of only what changed since the last scan.
- 🕰️ **Durable history** — an append-only timeline of every ring change, persisted in a portable JSONL log that survives a lost database. See [docs/persistence.md](docs/persistence.md).
- 🆚 **Comparison matrices** — side-by-side "Cline vs Aider vs Goose" across rings, risk, and rubric dimensions.
- 🧪 **Sandbox playbooks** — a safe, disposable trial recipe per tool. See [docs/sandbox-playbook.md](docs/sandbox-playbook.md).
- 🔌 **MCP server** — query the radar from Claude / Codex / any MCP client ("what should I try this week?").
- 🖥️ **Local dashboard** + 📄 **static export** for GitHub Pages.
- 🎨 **Fun lane** — playful local-AI projects (image gen, voice, LLM toys) tracked in their own category.

## Categories

`coding_agents` · `general_agents` · `mcp_tooling` · `sandbox_governance` · `agent_frameworks` · `model_serving` · `ai_infrastructure` · `physical_ai_infrastructure` · `fun_experimental`

51 curated sources ship by default; add your own from the CLI or the dashboard.

---

## Install

Requires Python 3.12+. Uses [uv](https://github.com/astral-sh/uv).

```bash
git clone <your-fork-url> onprem-ai-adoption-radar
cd onprem-ai-adoption-radar
uv venv && uv pip install -e ".[dev]"
```

## Quick start

```bash
uv run radar init                  # create local config + data dirs
uv run radar scan --days 30        # collect, score, and produce decision cards
uv run radar report                # print the decision report
uv run radar serve                 # dashboard at http://127.0.0.1:8765
```

> **GitHub rate limits:** scanning many GitHub sources unauthenticated hits the 60 req/hr limit. Export a token first — `export GITHUB_TOKEN=$(gh auth token)` (or any PAT) — for 5000 req/hr.

## CLI

| Command | What it does |
| --- | --- |
| `radar init` | Create `data/config.yaml` (from the seed list) and data directories. |
| `radar scan --days N` | Collect → classify → score → calibrate → cards. Writes report, Try This Week, and history artifacts. |
| `radar report [--json]` | Print the decision report from the latest scan (`--json` for scripting). |
| `radar history [--project X]` | Print the cumulative per-project timeline. |
| `radar compare --category X` / `--projects "A,B"` | Side-by-side comparison matrix. |
| `radar sandbox --project X` | Disposable trial plan (steps, teardown, cautions). |
| `radar seed add --id … --type … --project … --category … --url …` | Add a new source. |
| `radar seed list` | List the configured sources with type, category, and flags. |
| `radar export --out _site` | Render a self-contained static HTML snapshot. |
| `radar serve [--port 8765]` | Run the local dashboard. |
| `radar mcp` | Run the MCP server over stdio. |

## How it works

```
sources ──▶ collect ──▶ firehose classify ──▶ dedupe ──▶ score ──▶ build cards
(GitHub,            (entry→project,                      (7 dims +   (+ hybrid ring
 RSS, manual)        deterministic +                      on-prem      calibration)
                     optional LLM)                        rubric)
                                                                          │
        ┌─────────────────────────────────────────────────────────────────┤
        ▼                    ▼                      ▼                       ▼
   report.md           try-this-week.md       history (JSONL+DB)      dashboard / MCP
   (snapshot)          (delta only)           (durable timeline)      / compare / export
```

### Scoring & rings

Each signal is scored 1–5 on seven dimensions (workflow impact, laptop runnability, open-source maturity, on-prem relevance, security posture, demo value, setup friction) plus a deterministic on-prem rubric. Rings are then **calibrated across the batch**:

- **Absolute gates** always hold: `avoid` for a security blocker or a very low score; `adopt` for genuine excellence (and security ≥ 3).
- **Relative promotion** fills `adopt` up to a bounded target (~top fifth) from strong, secure candidates, ranked by score then on-prem relevance — so a cluster of tied scores never floods `adopt`.
- The bottom quartile drops to `watch`.

This keeps decisions meaningful on real, compressed score distributions instead of collapsing everything into one ring.

### Firehose classification

A blog feed is one source but covers many subjects. Firehose feeds (`firehose: true`) have each entry re-attributed to a **tracked project** by deterministic, normalized name/alias/slug matching; unmatched entries are dropped (counted, never silently). An **optional** LLM analyst (off by default, local-first / OpenAI-compatible) can take a constrained second pass at the dropped tail — it only maps to existing projects, never invents them.

### History & durability

The timeline (first-seen, every ring change) is the radar's most valuable data. It is stored as an **append-only `data/history.jsonl` log** — the source of truth — with SQLite as a fast, rebuildable cache. Delete the database and the next scan reconstructs the full timeline from the log. To keep it across machines or CI, back up or commit that one file. Full details and guarantees in **[docs/persistence.md](docs/persistence.md)**.

## MCP server

Expose the radar to AI clients so they can query it directly:

```jsonc
{
  "mcpServers": {
    "radar": {
      "command": "radar",
      "args": ["mcp", "--root", "/path/to/onprem-ai-adoption-radar"]
    }
  }
}
```

Tools: `list_recommendations`, `try_this_week`, `get_project` (with history), `list_tracked_projects`, `compare`, `sandbox_plan`.

## Dashboard

`radar serve` →
- `/` — decision cards
- `/compare` — comparison matrices by category or project set
- `/history` — per-project timelines
- `/sources` — list and add sources via a form

## Configuration

Sources live in `config/seed-sources.yaml` (copied to `data/config.yaml` on `init`). A source:

```yaml
- id: github-vllm
  type: github_repo        # github_repo | rss | manual
  enabled: true
  project: vLLM
  category: model_serving
  url: https://github.com/vllm-project/vllm
  tags: [model-serving, self-hosted, on-prem-relevant]
  # firehose: true         # (rss) reclassify entries to tracked projects
  # aliases: [vllm]         # extra match strings for the classifier
```

Add one without editing YAML: `radar seed add …`, or the dashboard's `/sources` form.

The optional LLM analyst is configured under `llm:` (disabled by default):

```yaml
llm:
  enabled: false
  base_url: http://localhost:11434/v1   # Ollama-style, OpenAI-compatible
  model: qwen2.5:3b
  api_key_env: RADAR_LLM_API_KEY
```

## Publishing (GitHub Pages)

`.github/workflows/publish.yml` scans on a daily schedule, exports a static site, and deploys it to GitHub Pages — carrying `data/history.jsonl` across runs so the public timeline accumulates. Enable once via **Settings → Pages → Source: GitHub Actions**. `ci.yml` runs the test suite on every push/PR.

## Project layout

```
src/radar/
  collectors/   github, rss, manual, registry
  pipeline/     classify (firehose), dedupe, delta, quotas, cards, llm_classify
  scoring/      deterministic, rings, calibrate
  storage/      config, database, run_store, history_store, history_log, seed_store
  reports/      markdown, try_this_week, history, comparison, sandbox
  mcp_server/   queries, server
  web/          app, templates, static_site
docs/           persistence.md, sandbox-playbook.md, seed-research.md
```

## Development

```bash
uv run pytest --cov    # 168 tests, coverage floor 80% (currently ~92%)
uv run ruff check src tests
uv run mypy
```

Conventions: deterministic core (no LLM in the default path), immutable data flow, many small focused modules, test-driven. Each feature lands via TDD with the timeline/decisions verified against real scans. CI runs lint (ruff), type checks (mypy), and the test suite with coverage on Python 3.12 and 3.13. See [docs/architecture.md](docs/architecture.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

Released into the **public domain** under [The Unlicense](LICENSE) — do anything you want with it, no attribution required.
