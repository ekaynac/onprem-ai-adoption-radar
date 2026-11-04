# Radar Pulse

Radar Pulse is what this repository does: **new models, papers, repositories
and news for an AI developer, triaged and ranked, fully unattended.** This page covers how it works end to end and how to
operate it. The classifier has its own page: [jev.md](jev.md).

## The daily experience

| Where | What |
|---|---|
| **Site homepage** (`/`) | Four lanes (New models, Papers, Repositories, News). The first 15 of each lane show, "Show all N" reveals the rest. A period filter offers the last 24 h, 7 days, or the whole window. Uncertain and filtered-out items appear in collapsible sections with the reason for each. Every item carries an engine badge (`jev`, `lineage`, `rules`, `untriaged`) and its ranking reasons. |
| **RSS** | `pulse.xml` (all lanes) plus `pulse-models.xml`, `pulse-papers.xml`, `pulse-repos.xml` and `pulse-news.xml`. TOP items only, newest first. |
| **Telegram** (Memati) | One message a day after 08:00 Istanbul: the top 6 models, 5 papers, 5 repos and 8 news items as numbered one-liners. Each line has a linked short title, owner, one signal (♥ likes, ▲ upvotes + "kod", ★ stars/day, or the source name) and a one-sentence Turkish explanation. "+N daha sitede" per lane, then a site · RSS footer. |
| **Alarms** (Çakır) | Only when something is wrong, once when it starts and once when it clears. |
| **JSON** | `data/pulse.v1.json` on the site: the public contract (below). |

## Pipeline

```
GitHub Actions publish.yml (every 2 h, a few minutes)
  radar pulse collect     newest uploads of 30 lab orgs + HF daily papers
                          + new GitHub repos (14 GitHub topics) + 16 news feeds
                          → data/pulse/items.jsonl (14-day window)
                          → data/pulse/health.json (latest outcome per source)
  radar pulse triage      Jev labels (rules fallback) → data/pulse/labels.jsonl
  radar pulse export      built frontend + data/pulse.v1.json + RSS → GitHub Pages

homelab ct-radar (every 30 min)
  radar pulse telegram --view-url … --summaries claude-cli
                          reads the published pulse.v1.json,
                          one Turkish sentence per shown item (Claude),
                          sends the daily digest once
  radar pulse watchdog    dead-man checks → Çakır
```

Everything is configured in `config/pulse.yaml` (sources, window, budgets,
watchdog) and `config/pulse-questions.yaml` (what Jev is asked).

### Lanes and sources

| Lane | Source | Notes |
|---|---|---|
| Models | `huggingface.co/api/models?author=<org>&sort=createdAt`: the 20 newest uploads of each lab org | Asking each lab for its newest uploads cannot miss a release. Each new original/unknown model gets the first prose paragraph of its **model card** (`sources/cards.py`, read once, up to `card_limit: 40` per run). That paragraph feeds the site row, RSS, Jev and the Turkish sentence. |
| Papers | `huggingface.co/api/daily_papers` (100/day) | Carries upvotes and code links. No keyword gate, no human approval. |
| Repos | GitHub search, one query per topic: created inside the window, at least 50 stars | Velocity is stars/day since creation, so one observation is enough. |
| News | 16 news feeds | Lab blogs (OpenAI, Google DeepMind, Google, Mistral, NVIDIA, MSR, GitHub), practitioners (Simon Willison, Latent Space), serving stacks (vLLM, Ollama, Hugging Face), Hacker News. Excluded feeds (Anthropic and Meta publish no RSS, the Qwen blog is stale) are listed with reasons in the config. |

A failing source never hides: each fetcher reports its errors per request,
`data/pulse/health.json` keeps the latest outcome of every source, the site
names failing sources, and the watchdog alerts on them.

### Model origin, without a model

`src/radar/pulse/lineage.py` classifies every new Hub repo from its tags and
name:

- **original**: a lab release (a lab org with no base model, a lab's own
  fine-tune, or a lab building on another lab's base, such as
  `apple/LensVLM-9B` on Qwen3.5-9B);
- **variant**: the lab's own quant, format or adapter of its release;
- **derivative**: anyone else's quant, fine-tune, merge or re-upload;
- **unknown**: not provable, so the classifier decides.

### Triage and ranking

See [jev.md](jev.md): fact questions per lane, confidence thresholds, readable
ranking rules, per-run token budget, circuit breaker, visible fallback.

## Telegram digest

`src/radar/pulse/telegram.py`

- **Exactly once**: delivered item ids and the last send date live in
  `$RADAR_STATE_DIR/telegram-state.json`. Overflow items (the ones behind
  "+N daha sitede") are recorded as seen, so nothing piles up. The day is
  marked sent only after every message went out, so a failed send retries the
  same day.
- **Token safety**: the Bot API token sits inside the request URL. Errors are
  rewritten without it and httpx request logs are silenced (tested).
- **Only a `sendMessage` caller**: the bots belong to the owner's openclaw
  setup, and the worker never polls `getUpdates`, so it cannot take their
  messages.

### Turkish explanations (Claude, subscription)

`src/radar/pulse/summaries.py`: one sentence per *shown* item, generated
once and cached in `$RADAR_STATE_DIR/summaries.json`. It runs one headless
`claude -p` call a day (model `haiku`) on the owner's subscription via
`CLAUDE_CODE_OAUTH_TOKEN`. There is no API key anywhere.

- Item text is framed as untrusted data. `--tools ""` disables every
  built-in tool, `--strict-mcp-config` loads no MCP servers,
  `--no-session-persistence` keeps no session files, and the process runs in
  an empty temp directory.
- The Claude process gets only `CLAUDE_CODE_OAUTH_TOKEN`, `HOME`, `USER`,
  `LOGNAME`, `PATH` and the locale: never the Telegram tokens.
- Output is validated: requested ids only, HTML stripped, ≤200 chars, escaped
  again when rendered.
- It is best effort. If Claude fails, the digest still goes out without the
  sentences, and the reason (CLI `terminal_reason`) is logged.

## The homelab worker (`ct-radar`)

Setup, secrets and verification: [`deploy/homelab/README.md`](../deploy/homelab/README.md)
and the homelab repo's `docs/services/radar.md` (unprivileged LXC 105,
`10.10.0.6`, outbound only, no GitHub credentials).

- **It never pulls code on its own.** Code changes only through
  `pct exec 105 -- /usr/local/bin/update-radar`, which shows the pending
  commits and asks first. Data arrives as the published `pulse.v1.json`,
  schema-checked on read.
- **Claude Code** comes from Anthropic's signed apt repository, with the key's
  fingerprint verified by the runbook. apt installs never self-update.
- **Secrets** live in `/etc/radar/env` (root:radar 0640): the Memati and Çakır
  bot tokens, the chat id and the Claude token. To renew the Claude token
  (yearly), run this on the Mac:
  ```
  bash deploy/homelab/set-claude-token.sh
  ```
  It runs `claude setup-token` in a 1000-column pseudo-terminal (a wrapped
  token lost characters), validates every candidate inside ct-radar, and
  writes the accepted one over SSH stdin. The token is never printed.

## Watchdog (`radar pulse watchdog`)

It reads public endpoints only, every 30 minutes, and alerts through Çakır
once per problem, then once when it clears:

| Key | Condition |
|---|---|
| `site-stale` / `site-unreachable` | live `pulse.v1.json` older than 6 h (three missed publishes) or unreachable |
| `publish-failing` | two consecutive failed `publish` runs on `main` (cancelled runs ignored) |
| `lane-empty:*`, `source:*` | a lane with no items, a Pulse source fully down (`error`); a `partial` source is shown on the site, not alarmed |
| `triage-degraded` | most shown items ranked without Jev |
| `digest-missing` | no Telegram digest by 10:00 Istanbul |
| (systemd `OnFailure`) | the worker unit itself failed → `notify-failure.py` |

Known blind spot: if the whole host is down, nothing inside it can speak.

## Operating it

```bash
# see what readers see, with reasons
uv run radar pulse top --lane model --limit 20
uv run radar pulse top --lane news --limit 30 --show-hidden

# rebuild locally (data/ is bot-owned: do not commit local changes to it)
uv run radar pulse collect && uv run radar pulse triage

# build and serve the site locally
npm run build --prefix frontend
uv run radar pulse export --out _site && python3 -m http.server -d _site 4173

# preview the digest without sending
uv run radar pulse telegram --dry-run --site-url https://ekaynac.github.io/onprem-ai-adoption-radar/

# on the homelab host
pct exec 105 -- journalctl -u radar-worker -n 30 --no-pager
pct exec 105 -- /usr/local/bin/update-radar          # deliberate code update
```

### Quality feedback loop

When a digest misses something ("X came out, why is it not there?") or shows
noise ("Y is useless"), that example becomes a regression test, the way the
K1 release test pins real releases, and the rule or question is adjusted.
This replaced an up-front gold set that could not be labeled in the abstract.

## Code map and the public contract

```
src/radar/
  cli.py                 radar pulse <collect|triage|top|export|telegram|watchdog>
  pulse/
    items.py             PulseItem, Lane: the one item model
    sources/             huggingface.py, cards.py, github.py, news.py (+ SourceRun)
    pipeline.py          collect = fetch all → merge → card summaries → persist
    store.py, health.py  data/pulse/items.jsonl, data/pulse/health.json
    lineage.py           model origin from Hub tags (no model needed)
    questions.py, jev.py, classify.py, triage.py   Jev labels, rules fallback
    rank.py              deterministic ranking with reasons
    view.py, feeds.py, export.py                   pulse.v1.json, RSS, site
    telegram.py, summaries.py, watchdog.py         homelab delivery and alarms
    env.py, http.py, text.py                       secrets, retries, text helpers
```

Dependencies point one way: sources → pipeline → triage/rank → view →
export/telegram. Nothing in `pulse/` imports outside it.

**`data/pulse.v1.json` is the integration point.** The site, RSS and the
homelab worker all read it, and `view.validate_view` pins its schema
(`pulse-v1`). A future consumer, for example InfraMedic's knowledge layer,
should read this file over HTTPS the same way rather than import Pulse code or
read `data/pulse/`; a schema change means a new version (`pulse-v2`) published
next to the old one until every reader moved.

## History

Until 2026-11-04 this repository also carried an on-prem "intelligence"
platform (catalog, technique radar, capacity planner, hardware catalog,
weekly brief, MCP server and API). Pulse replaced it; it was frozen on
2026-09-30 and deleted in Faz 7. Everything is recoverable from the git tag
`pre-slim-2026-11-04`.

The rescue plan with every measurement and decision behind Pulse:
[`reports/2026-09-29-radar-rescue-research-and-plan.md`](reports/2026-09-29-radar-rescue-research-and-plan.md)
(Turkish).
