# AI Radar

**New models, papers, repositories and news for an AI developer: collected,
triaged and ranked every two hours, fully unattended.** Open the site, read
the RSS, or get one Telegram message a morning with the top items and a
one-sentence Turkish explanation each.

Built by Enes Kaynakcı (Software Engineer, Mega Bilgisayar) to stay current
while building with AI. The live site is
**<https://ekaynac.github.io/onprem-ai-adoption-radar/>**.

## Radar Pulse (the front door)

| | |
|---|---|
| 🧠 **New models** | The newest uploads of 30 lab orgs on Hugging Face, with quants, GGUF packs, merges and re-uploads told apart from real releases by `base_model` tags, no model needed ([docs/pulse.md](docs/pulse.md#model-origin-without-a-model)) |
| 📄 **Papers** | Hugging Face daily papers, ranked by upvotes, topic and whether they ship code or weights |
| 🧰 **Repositories** | New GitHub repos by star velocity; lists, courses and demos filtered out, with the reason shown |
| 📰 **News** | Lab blogs (OpenAI, Google DeepMind, Mistral, NVIDIA, Microsoft Research…), practitioners and Hacker News, ranked by what happened × source authority |

- **Triage by [Jev](docs/jev.md).** TypeSafe's classifier answers *facts*
  per item (what kind of event, what kind of repo, paper topic, does it ship
  code). Readable rules turn those facts into a ranking, and every position
  shows its reasons. It costs well under $1 a month. When Jev is down, rules
  take over visibly and upgrade later.
- **Nothing hidden.** The site and `pulse.v1.json` carry every item in the
  14-day window, including uncertain and filtered-out ones with their
  reasons. Ranking only orders items.
- **Delivered.** The homepage shows four lanes. RSS comes as `pulse.xml` plus
  one feed per lane. The Telegram digest runs daily from a homelab worker via
  the owner's bot, and its Turkish explanations come from Claude on the
  owner's subscription, with every tool disabled.
- **Watched.** A dead-man watchdog alerts once when the site goes stale,
  publish fails twice, a lane empties, triage degrades or the digest is
  missing, and once more when the problem clears.

How it works, operations and the homelab worker: **[docs/pulse.md](docs/pulse.md)**.
How the classifier is used, what it costs and how to change it:
**[docs/jev.md](docs/jev.md)**. The rescue plan and measurements behind all of
this (Turkish): [docs/reports/2026-09-29-radar-rescue-research-and-plan.md](docs/reports/2026-09-29-radar-rescue-research-and-plan.md).

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Tests](https://img.shields.io/badge/tests-passing-brightgreen)
![Classifier](https://img.shields.io/badge/triage-Jev%20%2B%20rules%20fallback-blueviolet)
![License](https://img.shields.io/badge/license-MIT-blue)

## Also in this repository

The project began as an on-prem **adoption radar**, and those parts still run
alongside Pulse:

- **Adoption radar**: deterministic `adopt` / `pilot` / `watch` / `avoid`
  rings for tracked projects, per-project evidence, comparisons and history.
  A curated source list ships in `config/seed-sources.yaml`, and the source
  autopilot grows it weekly.
- **Intelligence catalog**: canonical releases with cited claims, benchmark
  triangulation (self-reported vs. independent leaderboards), the release
  stream and the Answer Machine (`/ask`, task + hardware → a cited
  recommendation). The pipeline re-evaluates persisted trusted claims weekly.
- **MCP server**: ask the radar from Claude, Codex or any MCP client.

**Frozen since 2026-09-30** (no longer refreshed; reachable under
"Frozen · retiring" until the delete decision on 2026-10-28): the weekly brief
and calls ledger, the Newsroom, stack-profile alerts, the deployment planner,
the hardware catalog, and lineage backfill.

### Adoption radar capabilities

- 🧭 **Decision rings** — `adopt` / `pilot` / `watch` / `avoid`, from a deterministic 7-dimension score + on-prem rubric.
- ⚖️ **Hybrid ring calibration** — absolute gates (security/excellence) plus a quartile-aware, size-capped promotion so rings actually discriminate and "Try This Week" stays a short, high-conviction list.
- 🔬 **Evidence-based scoring** — decisions move on *observed data*, not just config tags: star growth and release cadence between scans, days-since-push, and **known security advisories (OSV.dev)** that cap a project's security score. Cards explain themselves with an "Observed" section.
- 🚨 **License-change & upgrade-risk detection** — a tracked project flipping `Apache-2.0 → BUSL` is flagged the scan it happens; release notes are scanned for breaking changes / migrations / security fixes and surfaced as an upgrade-risk level.
- 📈 **Momentum & movers** — `rising` / `falling` / `steady` per project from the accumulated timeline; reports open with a **Movers** section and the dashboard shows trend arrows.
- 🏢 **Provider / backer at a glance** — every project is tagged with who stands behind it (🏢 Big Tech · 🚀 Startup · 🌐 Community · 👤 Individual · 🎓 Academic), shown as a colored badge on the index and project pages, filterable, and exposed over MCP.
- 📌 **Overrides & decision journal** — pin a ring with a reason (`radar override`), record trial outcomes (`radar trial`); pins win over the computed ring and **drift is surfaced**, not hidden.
- 🎛️ **Scoring profiles** — re-rank the same data through `security-first` / `solo-dev` / `demo-hunter` lenses without a re-scan.
- 📄 **Per-project pages** — a full view per project (score breakdown, rubric, evidence, advisories, metrics history, ring timeline) on both the dashboard and the published static site.
- 🔎 **Search & filter** — category + text filtering on the index, working identically on the live dashboard and the static site (no build step).
- 🩺 **Scan health** — collector/enrichment/firehose warnings from the latest scan, surfaced on the dashboard, static site, and `radar scan` output.
- 🧮 **Backtest** — `radar backtest` re-scores history to show how a profile or a config change would have moved past decisions, so scoring is tuned with evidence, not guesswork.
- ♻️ **Offline replay** — re-score a past run's raw signals with current config (`radar scan --replay`) to tune scoring with zero network.
- 📡 **Firehose classification** — broad vendor blogs are re-attributed entry-by-entry to the projects they mention. Deterministic matching with an **optional, off-by-default LLM** second pass for the ambiguous tail.
- 🩺 **Source health** — sources that go quiet for several scans are flagged as likely-dead feeds in `radar seed list`.
- 🛰️ **Auto-discovery** — `radar discover` proposes fast-rising untracked GitHub repos for review (never auto-added).
- 🔔 **Webhooks & subscribable feeds** — optional post-scan webhook (Slack/Discord/Teams or generic JSON) on ring changes; the static site publishes Atom, RSS 2.0, and JSON change feeds.
- 🆕 **Delta / "Try This Week"** — a separate report of only what changed since the last scan.
- 🕰️ **Durable history** — an append-only timeline of every ring change, persisted in a portable JSONL log that survives a lost database. See [docs/persistence.md](docs/persistence.md).
- 🆚 **Comparison matrices** — side-by-side "Cline vs Aider vs Goose" across rings, risk, and rubric dimensions.
- 🧪 **Sandbox playbooks** — a safe, disposable trial recipe per tool. See [docs/sandbox-playbook.md](docs/sandbox-playbook.md).
- 🔌 **MCP server** — query the radar from Claude / Codex / any MCP client ("what should I try this week?").
- 🖥️ **Local dashboard** + 📄 **static export** for GitHub Pages — redesigned with a hero, ring-distribution stats, ring pills, a legend, sticky filters, and automatic dark mode.
- 🟦 **Mega Bilişim corporate brand** — Process Blue `#009FDA` hero with the *mega®* lockup, Cool Gray surfaces, Centrale Sans type, and a subtle Buka dot-pattern, following the Mega design standard (light + dark). Generated with the Open Design app and ported into the shared design system.
- ♾️ **Runs itself** — a two-hour GitHub Action scans, gates, and republishes; it commits the history log back to the repo, which keeps the timeline durable **and** keeps the schedule from auto-disabling, so the public site survives untouched.
- ⬇️ **Downloadable data** — the full append-only timeline (`history.jsonl`) and change feeds (Atom/RSS/JSON) are published next to the site and served by the dashboard at `/history.jsonl`.
- 🎨 **Fun lane** — playful local-AI projects (image gen, voice, LLM toys) tracked in their own category.
- 🎓 **Research technique radar** — curated academic techniques (speculative decoding, PagedAttention, LoRA, ReAct…) get their own deterministic rings, scored by *which tracked tools already implement them* plus citation evidence — research verdicts move when tool verdicts move. Browsable at `/research` (dashboard + static site) with per-technique pages showing a research→production timeline, queryable over MCP (`list_techniques`/`get_technique`/`technique_movers`), and published as Atom/JSON change feeds. Tool and model pages cross-link back: each shows the research techniques it implements, and tool cards carry an "Implements N tracked research techniques" evidence line.
- 📈 **Trending radar** — a daily two-lane GitHub sweep (strict on-prem identity + broader AI heat) appends to a committed observation log, so the radar computes real star *velocity* and flags newly-created repos — the foundation for self-growing catalogs and a githubsignals-style trending feed. A weekly **source autopilot** then auto-adds the strict-lane repos that clear every gate (sustained star momentum, size + permissive-license floors, a confident category, denylists) straight into the tracked catalog — the radar growing itself, with `auto-added` provenance and a committed audit log. Browsable at `/trending` (dashboard + static site) with two lanes — on-prem radar candidates and "elsewhere in AI" — plus a top-3 strip on the index and an MCP `list_trending` tool. A weekly **digest** rolls the week's trending + auto-adds + ring changes into a shareable page, Atom/RSS newsletter feeds, a webhook ping, and Mega-branded social cards (SVG → PNG in CI). `/trending` is now a hub — alongside repos it surfaces **trending models** (fastest-rising by download growth) and **trending techniques** (by citation momentum), each with the items new or promoted this week; model download-velocity is made durable by a committed `data/model-metrics.jsonl` log. `/trending` also surfaces **emerging models** — untracked HF-trending models observed over time in `data/model-candidate-observations.jsonl`, ranked by download velocity — and the catalog autopilot only auto-adds a model once it shows **sustained** download momentum, not just a high absolute count. …and **emerging papers** — untracked hot arXiv/HF papers observed over time in `data/technique-candidate-observations.jsonl`, ranked by HF-upvote velocity — round out the hub; papers stay human-reviewed (no auto-add), surfaced for a person to promote. Emerging rows now display a "Last seen" date and STALE badge when a candidate stops appearing in daily sweeps, and both trending and model promotion momentum gates measure sustained growth over the last 14 days — "rising right now" — ensuring decisions reflect current activity rather than historical accumulation.
- 🧰 **Platform capability matrix** — `/platforms` (dashboard + static site) is a cited hardware/feature support matrix for 8 on-prem serving engines (vLLM, SGLang, TensorRT-LLM, llama.cpp, Ollama, MLX-LM, TGI, LMDeploy): which support which GPU/NPU family and which serving feature (tensor/pipeline/expert parallel, MLA, hybrid attention, FP8/NVFP4/AWQ/GPTQ/GGUF, FP8 KV cache, speculative decoding, prefix caching, disaggregated prefill). Every cell traces to a doc/README/release-note citation and a verified date — `unknown` is the honest default when a claim can't be confirmed, never a guessed "yes". Queryable over MCP (`get_platform_support`).
- 🧮 **Capacity planner** — answers the north-star question *"how many H200s for DeepSeek-V4-Pro at N users?"* deterministically: architecture-correct KV math (MLA/GQA/hybrid), per-rank TP/PP/EP memory, roofline throughput, and a two-direction solver (`radar capacity plan` finds the smallest fleet that clears a target, `radar capacity max` finds the largest concurrency a fixed fleet can serve), plus copy-pasteable vLLM/SGLang/TensorRT-LLM launch recipes and a kW-first TCO estimate (tokens/s/kW, with `$/Mtok` honestly marked electricity-only where no public list price exists). Every answer carries its assumption sheet — the exact constants and fallbacks behind the number, never a silent guess. Queryable over MCP (`plan_capacity`/`max_workload`/`compare_devices`).

Everything new degrades gracefully and stays off the critical path: enrichment (OSV/HN/downloads) and webhooks are best-effort and never fail a scan, and the default scoring path remains fully deterministic and offline.

## Categories

`coding_agents` · `general_agents` · `mcp_tooling` · `sandbox_governance` · `agent_frameworks` · `model_serving` · `ai_infrastructure` · `physical_ai_infrastructure` · `fun_experimental`

A curated source list ships by default (grown weekly by the source autopilot); add your own from the CLI.

---

## Install

Requires Python 3.12+. Uses [uv](https://github.com/astral-sh/uv).

```bash
git clone https://github.com/ekaynac/onprem-ai-adoption-radar.git
cd onprem-ai-adoption-radar
uv venv && uv pip install -e ".[dev]"
```

## Quick start

```bash
uv run radar init                  # create local config + data dirs
uv run radar intelligence-migrate --root .
uv run radar intelligence-run discovery --root .
uv run radar scan --days 30        # collect, score, and produce decision cards
uv run radar report                # print the decision report
uv run radar serve                 # dashboard at http://127.0.0.1:8765
```

> **GitHub rate limits:** scanning many GitHub sources unauthenticated hits the 60 req/hr limit. Export a token first — `export GITHUB_TOKEN=$(gh auth token)` (or any PAT) — for 5000 req/hr.

## CLI

| Command | What it does |
| --- | --- |
| `radar pulse collect` | Newest lab-org models and HF daily papers, plus the repo and news logs, into `data/pulse/items.jsonl` (14-day window). |
| `radar pulse triage` | Label new items with Jev (`TYPESAFE_API_KEY`), falling back to rules; prints tokens and cost. |
| `radar pulse top --lane <model\|paper\|repo\|news>` | A lane's ranking with the reasons behind every position (`--show-hidden` includes filtered items). |
| `radar pulse telegram` | The daily digest (`--dry-run` to preview, `--summaries claude-cli` for Turkish explanations, `--view-url` to read the published view). |
| `radar pulse watchdog` | Dead-man checks with once-only alerts (`--dry-run` to only print). |
| `radar pulse gold-sample` / `radar pulse eval` | Owner-labelled gold set and Jev-vs-rules scoring against it. |
| `radar intelligence-migrate` | Idempotently import legacy catalogs into canonical SQLite/Postgres storage. |
| `radar intelligence-replay-events` | Restore the committed intelligence event mirror into the canonical projection. |
| `radar intelligence-run discovery` | Sweep Hugging Face, official GitHub releases, and configured feeds for the current two-hour window. |
| `radar intelligence-run verify-new` | Verify newly detected releases in the current two-hour window. |
| `radar intelligence-run enrichment` | Refresh model metadata, configs, model cards, artifacts, and cited claims. |
| `radar intelligence-run verification` | Re-evaluate trusted claims and route conflicts to review. |
| `radar intelligence-run qualification` | Apply category-specific deployability and platform-fit gates. |
| `radar intelligence-run recommendations` | Compute the public on-prem decision for qualified releases. |
| `radar intelligence-scheduler` | Run the two-hour, daily, and weekly policy in a long-lived local process. |
| `radar init` | Create `data/config.yaml` (from the seed list) and data directories. |
| `radar scan --days N` | Collect → classify → enrich → score → calibrate → cards. Writes report, Try This Week, and history artifacts. |
| `radar scan --replay <run-id>` | Re-score a past run's raw signals offline with current config (no network, no persistence). |
| `radar scan --profile <name>` | Score through a named profile (re-weighted dimensions). |
| `radar report [--json] [--profile X]` | Print the decision report from the latest scan. |
| `radar movers` | Show each project's direction of travel (rising / falling / steady). |
| `radar calibrate-report [--check]` | Diagnose whether the scoring discriminates; `--check` exits non-zero on collapse (CI gate). |
| `radar backtest [--profile X] [--runs N]` | Re-score past runs and report how rings would differ — under a profile's weights, or current config vs each run's persisted decision (read-only). |
| `radar override --project X --ring R --reason "…"` | Pin a project's ring (`--clear` to remove); drift vs the radar is surfaced. |
| `radar trial --project X --outcome adopted\|rejected\|inconclusive` | Record a trial outcome in the decision journal and timeline. |
| `radar discover [--category X] [--min-stars N]` | Propose trending untracked GitHub repos to `data/proposed-seeds.yaml`. |
| `radar history [--project X]` | Print the cumulative per-project timeline. |
| `radar compare --category X` / `--projects "A,B"` | Side-by-side comparison matrix. |
| `radar sandbox --project X` | Disposable trial plan (steps, teardown, cautions). |
| `radar seed add --id … --type … --project … --category … --url …` | Add a new source. |
| `radar seed list` | List sources with type, category, flags, and dead-feed (stale) status. |
| `radar research scan` | Score seeded research techniques: closed-loop vs the radar's own tool/model rings + citations (Semantic Scholar/OpenAlex, best-effort). |
| `radar research list [--ring R] [--domain D] [--category C]` | List techniques from the latest research scan. |
| `radar research show <id>` | One technique: score breakdown, papers, implementations, ring history. |
| `radar research track-record` | Paper→radar lag per technique (median + per-row; predictive hit-rate accrues with history). |
| `radar trending scan` | Sweep GitHub for trending/new repos (two lanes) and append to the observation log. |
| `radar news scan` | Sweep the newsroom feeds (engine/vendor blogs, HN Algolia) into the append-only news store. |
| `radar news classify` | Classify news via Claude (API key or the local `claude` CLI); schema failures stay off product surfaces. |
| `radar desk brief` | Build this week's analyst brief and record its new calls (idempotent per week). |
| `radar desk auto-resolve` | Score open calls by the documented deterministic rules once their windows elapse. |
| `radar desk resolve <id> --outcome …` | Manually resolve a call when human judgment applies. |
| `radar models benchmarks scan` | Sweep public leaderboards into the triangulated benchmark store. |
| `radar intelligence-lineage-backfill` | Backfill lineage edges (budgeted: `--fetch-limit/--parent-limit/--max-minutes`) and infer name-fingerprint suggestions. |
| `radar trending list [--lane L] [--new]` | List trending repos with star velocity + NEW badges from the observation log. |
| `radar trending promote [--limit N] [--dry-run]` | Auto-add sustained-momentum strict-lane repos (all gates passed) into `config/seed-sources.yaml`, tagged `auto-added`. |
| `radar digest generate [--base-url URL]` | Build the weekly digest page + Mega-branded social cards + Atom/RSS newsletter feeds; append the digest log and fire the webhook. |
| `radar research discover [--source all\|hf\|arxiv]` | Propose technique candidates from HF daily papers and a recent arXiv category sweep, ranked by citations/day, to `data/proposed-technique-seeds.yaml` (human-reviewed, never auto-added). |
| `radar export --out _site` | Render a self-contained static HTML snapshot (+ change feeds). |
| `radar serve [--port 8765]` | Run the local dashboard. |
| `radar mcp` | Run the MCP server over stdio. |

## How it works

```
sources ─▶ collect ─▶ firehose classify ─▶ dedupe ─▶ enrich ─▶ score ─▶ build cards
(GitHub,          (entry→project,                   (OSV /     (7 dims +  (+ pins, ring
 RSS, manual)      deterministic + optional LLM)     HN /        on-prem    calibration,
                                                     downloads)  rubric +   movers)
                                                                 evidence)
                                                                          │
        ┌─────────────────────────────────────────────────────────────────┤
        ▼              ▼                ▼                  ▼               ▼
   report.md      try-this-week.md  history (JSONL+DB)  webhook +     dashboard / MCP
   (+ movers)     (delta only)      metrics + journal   change feeds  / compare / export
```

See [docs/architecture.md](docs/architecture.md) for the full module map and invariants.

### Scoring & rings

Each signal is scored 1–5 on seven dimensions (workflow impact, laptop runnability, open-source maturity, on-prem relevance, security posture, demo value, setup friction) plus a deterministic on-prem rubric. Rings are then **calibrated across the batch**:

- **Absolute gates** always hold: `avoid` for a security blocker or a very low score; `adopt` for genuine excellence (and security ≥ 3).
- **Relative promotion** fills `adopt` up to a bounded target (~top fifth) from strong, secure candidates, ranked by score then on-prem relevance — so a cluster of tied scores never floods `adopt`.
- The bottom quartile drops to `watch`.

This keeps decisions meaningful on real, compressed score distributions instead of collapsing everything into one ring.

### Firehose classification

A blog feed is one source but covers many subjects. Firehose feeds (`firehose: true`) have each entry re-attributed to a **tracked project** by deterministic, normalized name/alias/slug matching; unmatched entries are dropped (counted, never silently). An **optional** LLM analyst (off by default, local-first / OpenAI-compatible) can take a constrained second pass at the dropped tail — it only maps to existing projects, never invents them.

### History & durability

The legacy project timeline is stored in append-only `data/history.jsonl`, with
SQLite as its rebuildable query projection. Canonical intelligence additionally
uses `data/intelligence.db`, `data/intelligence/events.jsonl`, and
content-addressed raw snapshots. Back up the complete set for exact recovery;
full details and replay order are in **[docs/persistence.md](docs/persistence.md)**.

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

Flagship tools: `recommend` (What should I run? — ranked, cited candidates),
`whats_new` (What changed that touches THIS stack? — silence otherwise),
`benchmarks` (triangulated per-source table with flagged self-reported gaps),
`plan_capacity` / `max_workload` / `compare_devices`, plus 30+ more:
`list_recommendations`, `get_project`, `list_tracked_projects`, `compare`,
`sandbox_plan`, `search_intelligence`, `can_run`, `fit_report`, and the
technique/trending/source-health query set.

## Dashboard

`radar serve` exposes the local command center. The public static edition ships:

- `/` — the Answer Machine: task + hardware → a cited recommendation
- `/desk` — the weekly brief with verdicts, the calls ledger, and the public track record
- `/newsroom` — classified change intelligence with the raw firehose one filter away
- `/workspaces` — the stack-profile demo: alerts diffed against a reference estate
- `/advisor`, `/compare`, `/planner` — decision tools over the same engines
- Evidence appendix: `/catalog`, `/releases`, `/projects`, `/trending`, `/platforms`, `/hardware`, `/research`, `/overview`
- `/operations` and `/integrations` — source health, history downloads, feeds, API, and MCP guidance

Private workspace, mutation, review, and planner routes are not exposed by the
static public edition.

### Authentication

Both the API and the dashboard are **open by default** — this is intended for
local development. To protect every mutating endpoint (API writes and the
dashboard's `POST /sources` seed form), set a token:

```bash
export RADAR_API_TOKEN="your-secret"
```

Clients must then send `Authorization: Bearer your-secret` on non-GET API
calls; the dashboard form asks for the same header. Token comparison is
constant-time, and cross-origin form posts are rejected (CSRF guard). GET
endpoints always remain public — that is the product. If you expose either app
beyond localhost, front it with TLS and see [SECURITY.md](SECURITY.md) for the
full threat model.

## Freshness automation

GitHub Actions and the built-in scheduler enforce one platform-wide policy:

- every two hours: discover and verify new releases, refresh the legacy radar,
  enrich claims, qualify deployment readiness, refresh recommendations, and
  publish the complete static product;
- weekly: re-evaluate every persisted trusted claim and its evidence against
  current policy.

Pulse runs inside the same two-hourly `publish` job (`radar pulse collect`,
`radar pulse triage`). A homelab worker (`ct-radar`, every 30 minutes) sends
the daily Telegram digest and runs the dead-man watchdog. It never pulls code
on its own and holds no GitHub credentials. See [docs/pulse.md](docs/pulse.md)
and [deploy/homelab/README.md](deploy/homelab/README.md).

See [Intelligence operations](docs/intelligence-operations.md) for scheduler
modes, credentials, storage, backups, and incident recovery.

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
  package: {ecosystem: PyPI, name: vllm}  # enables downloads + OSV advisories
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

**Enrichment** (advisories, traction, downloads) is on by default; toggle per source class:

```yaml
enrichment:
  osv: true          # OSV.dev security advisories (caps security score)
  hackernews: true   # HN mention counts (community traction)
  downloads: true    # PyPI/npm weekly downloads
  advisory_window_days: 90
```

**Profiles** re-weight the seven dimensions for `--profile`; ships `security-first`, `solo-dev`, `demo-hunter`:

```yaml
profiles:
  security-first: {security_posture: 3.0, on_prem_relevance: 2.0, demo_value: 0.5}
```

**Notifications** post to a webhook on ring changes *and* on new stack-profile
alerts (`radar alerts notify`, exactly-once per alert via
`data/alerts-delivered.jsonl`). Off by default; the URL is read from the
environment:

```yaml
notify:
  enabled: false
  webhook_url: ${RADAR_WEBHOOK_URL}
  format: generic    # generic | slack | teams
```

`slack` posts `{"text": ...}` (Slack/Discord classic webhooks); `teams`
wraps the same text in the Adaptive Card envelope Microsoft Teams
Workflows webhooks require.

To activate in CI: set `enabled: true` in `data/config.yaml` and add a
`RADAR_WEBHOOK_URL` repository secret — until then each publish prints a
visible skip line.

## Publishing (GitHub Pages)

`.github/workflows/publish.yml` scans every two hours, exports the complete
static product, commits the durable history and intelligence artifacts, and
deploys once to GitHub Pages. Enable once via **Settings → Pages → Source:
GitHub Actions**. `ci.yml` runs the test suite on every push/PR.

## Project layout

```
src/radar/
  pulse/        Radar Pulse: items, sources, lineage triage, Jev client, triage,
                rank, view, feeds, telegram, summaries, watchdog
  intelligence/ canonical lifecycle, evidence, claims, freshness, jobs
  api/          FastAPI routes and OpenAPI contract
  capacity/     deterministic memory, throughput, fleet, and TCO planning
  collectors/   github, rss, manual, registry
  enrichment/   osv, hackernews, downloads, runner
  pipeline/     classify, dedupe, evidence, upgrade_risk, momentum, delta, quotas, cards, llm_classify
  scoring/      deterministic, rings, calibrate, profiles
  storage/      config, database, run_store, history_store, history_log,
                metrics_store, source_health_store, overrides_store, seed_store
  discovery/    github_trending, proposals
  notify/       webhook
  reports/      markdown, try_this_week, history, comparison, sandbox, movers, feeds
  mcp_server/   queries, server
  web/          app, templates, static_site
frontend/       React site (Pulse homepage) and static public shell
deploy/homelab/ ct-radar worker: systemd units, update-radar, set-claude-token
config/         pulse.yaml, pulse-questions.yaml (Jev questions), news-sources.yaml, seeds
docs/           pulse.md, jev.md, architecture.md, persistence.md, reports/
```

## Development

```bash
uv run pytest --cov    # coverage floor 80% enforced in CI
uv run ruff check src tests
uv run mypy
```

Conventions: deterministic scoring (classifiers answer facts; rules rank), immutable data flow, many small focused modules, test-driven. Each feature lands via TDD with the timeline/decisions verified against real scans. CI runs lint (ruff), type checks (mypy), and the test suite with coverage on Python 3.12 and 3.13. See [docs/architecture.md](docs/architecture.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the [Code of Conduct](CODE_OF_CONDUCT.md).

## Author

Built by **Enes Kaynakcı** — Software Engineer at **[Mega Bilgisayar Tic. Ltd. Şti.](https://www.megabilgisayar.com.tr)**.

## License

Released under the **[MIT License](LICENSE)** — © 2026 Enes Kaynakcı. Free to use, modify, and distribute; keep the copyright notice.
