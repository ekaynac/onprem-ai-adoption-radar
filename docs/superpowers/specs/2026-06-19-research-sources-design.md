# Research Sources (arXiv + HF Papers) — Design

Date: 2026-06-19
Status: approved (interactive brainstorm; all sections confirmed)

## Context

The radar tracks **adoptable tools** and places them on adopt/pilot/watch rings
with decision cards scored on adoption dimensions (laptop runnability, setup
friction, security posture, …). Academic sources — arXiv papers, Hugging Face
Papers — are not adoptable tools and must **not** become scored decision cards
(scoring a paper on "setup friction" is meaningless). But research is a strong
*leading indicator*, and the codebase already has the right machinery for it:
the Hacker News mention-counting enrichment and the discovery→proposals pipeline.

This sub-project adds research as two additive capabilities, reusing those
patterns, without disturbing the adoption-card model:

- **A. Paper-mention enrichment** — strengthen signals on tools we already track
  ("vLLM cited in 4 new papers this week", with the named papers as evidence).
- **B. Paper-driven discovery** — surface repos linked from trending papers as
  candidate new tools, for human review.

This is sub-project 1 of two. Sub-project 2 (tracking local model artifacts and
mapping them to hardware configurations) is explicitly **out of scope** here and
gets its own brainstorm → spec → plan cycle. The HF Papers feed built here is a
natural future input to that work.

## Non-goals

- No new scored category for papers; no paper ever becomes a decision card.
- No separate "research radar" page/view — this enhances existing tools and the
  existing discovery queue only.
- No LLM in the default path; deterministic, identical inputs → identical output.
- No model-artifact or hardware-config tracking (sub-project 2).

## Source-to-capability split

- **arXiv API → Capability A (mentions).** Broad corpus, best for counting
  citations of tracked tools. No API key.
- **HF daily-papers API → Capability B (discovery).** Curated, and most entries
  link a GitHub repo — clean candidates. No API key.

## Capability A — arXiv mention enrichment

- **New module** `src/radar/enrichment/arxiv.py`, modeled on
  `enrichment/hackernews.py`:
  `fetch_paper_mentions(paper_query, client, since) -> PaperMentions`.
  - Queries `http://export.arxiv.org/api/query` with
    `search_query=(all:<paper_query>) AND (cat:cs.AI OR cat:cs.LG OR cat:cs.CL OR
    cat:cs.DC OR cat:cs.SE OR cat:cs.CV OR cat:cs.RO)`,
    `sortBy=submittedDate&sortOrder=descending`. The category set
    (AI, ML, NLP, distributed, software-eng, vision, robotics) is a module
    constant so it is easy to tune.
  - Parses the Atom response with `feedparser` (already a dependency).
  - Filters client-side to entries with `published >= since`.
  - Returns a **count** plus **up to 5 most-recent** papers as `PaperRef`
    (title + abstract URL + published date).
- **Opt-in:** runs only for sources with a non-empty `paper_query`. A source
  without one is skipped — this keeps ambiguous/common-word names (Ray, Continue,
  Goose, Crush, Cua, garak) out of the signal. Precision over recall.
- **Pacing:** arXiv requests ≤1 request / 3 seconds; add light pacing/spacing so
  a scan stays a good citizen (and reuse the downloads-style bounded retry for
  transient failures where it fits).

## Data model & evidence flow

- **`ProjectMetrics`** gains `paper_mentions: int` (mirrors `hn_mentions`) —
  persisted per scan, time-series, momentum-eligible.
- **`PaperRef`** — small immutable model `{title: str, url: str, published_at}`.
- **`ProjectEvidence`** carries a `papers: list[PaperRef]` (mirroring how
  `advisories: list[Advisory]` already flows through `build_evidence`).
- **`evidence_notes()`** renders a line such as
  *"Cited in 4 recent papers: FlashInfer-2 (arxiv.org/abs/…), …"*. The named
  paper URLs join the card's existing `evidence` link set and the
  "Try This Week" entries. `paper_mentions` is momentum-eligible like other
  metrics (a rising paper-mention trend can contribute to "rising" movers).

## Capability B — HF Papers discovery

- **New module** `src/radar/discovery/hf_papers.py`, twin of
  `discovery/github_trending.py`:
  - Pulls the HF daily-papers API (JSON).
  - Extracts a linked GitHub repo per paper, best-effort, from the paper
    metadata; skip the paper if no repo can be resolved.
  - Drops repos already tracked and those **below the existing discovery star
    floor** (reuse the current threshold — precision-first, consistent with
    GitHub-trending discovery).
  - Best-effort maps the paper's subject tags → a radar `Category`; when
    uncertain, tag the proposal `needs-triage` so the human assigns a category
    on promotion.
  - Returns `SeedProposal`s written to the existing `data/proposed-seeds.yaml`
    review file. **Never auto-added** — a human disposes, same as today.

## Config & sources

- Add optional `paper_query: str | None = None` to `SourceConfig`
  (`models.py`), threaded through config load and the seed schema.
- Seed `paper_query` in `config/seed-sources.yaml` for distinctively-named,
  high-value tools (e.g. vLLM, SGLang, llama.cpp, TensorRT-LLM, LMDeploy,
  KServe, Triton Inference Server, Ray→needs a disambiguated query or stays
  off). Leave ambiguous names unset.
- HF Papers discovery is configured in the existing `enrichment`/discovery
  config block; default on, degrades gracefully when the API is unreachable.

## Error handling & cadence

- Both capabilities run inside the daily scan.
- Every network call is best-effort and wrapped like the existing enrichers
  (`enrichment/runner.py` `_safe()`): a failure appends to `enrichment_warnings`
  (Capability A) or the discovery warnings (Capability B) and **never fails the
  run**. These warnings are already surfaced on the dashboard/static site via the
  source-health work.
- No API keys required for either source.

## Testing

Mirror `tests/test_enrichment.py` and `tests/test_discovery.py`:

- `FakeClient` returning canned arXiv Atom and HF daily-papers JSON fixtures.
- A: assert count + named papers capped at 5; assert `published < since` is
  excluded; assert a source without `paper_query` is skipped; assert evidence
  notes render and paper URLs reach the card evidence set; assert graceful
  degradation (network failure → 0 mentions + warning, no raise).
- B: assert tracked repos and below-floor repos are dropped; assert a paper with
  no resolvable repo is skipped; assert category mapping + `needs-triage`
  fallback; assert proposals are written to the review file, never to config.
- Keep ruff + mypy clean and coverage ≥ 80%.

## Verification

- Unit suites above green; `ruff check src tests`, `mypy src`, `pytest -q` clean.
- Live smoke (optional, no key): run `fetch_paper_mentions("vLLM", …, since=14d)`
  and confirm a non-zero count with real paper titles/links; run the HF Papers
  discovery and confirm `proposed-seeds.yaml` gains repo-linked candidates not
  already tracked.
- Full scan (`radar scan --root . --days 7`, needs `GITHUB_TOKEN`): confirm
  `paper_mentions` appears in `project_metrics` for queried tools and the named
  papers render on those cards; confirm `enrichment_warnings` stays clean.

## Out of scope (sub-project 2, separate cycle)

Tracking local model artifacts (Llama, Qwen, DeepSeek, Mistral, gpt-oss…) and
mapping them to viable hardware configurations (VRAM by quantization, single- vs
multi-GPU, which tracked accelerators can run them). Different data model and
output shape; its own brainstorm → spec → plan.
