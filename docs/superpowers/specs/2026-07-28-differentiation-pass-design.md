# Differentiation Pass — Design

**Date:** 2026-07-28 · **Status:** approved direction, spec under review
**Owner:** Enes Kaynakcı (Mega Bilişim Teknolojileri)
**Context:** competitive analysis vs trendshift.io (2026-07-28). Companion to the
capacity-planning program (`2026-07-27-capacity-planning-radar-v3-design.md`);
runs as its own compact sub-project, off the C/D critical path.

## 1. Purpose

Trendshift.io owns "what's trending" (momentum rankings, trending-history
credential, README badges, sponsored placement). The radar's identity is one
layer up: **what to adopt, with receipts, and what it takes to run it.**
This pass adopts four of trendshift's proven presentation/growth mechanics —
re-grounded in data the radar already commits — and makes the radar's
decision-grade evidence visible at first glance.

Positioning line (used on the site hero and README):
> Trending tells you what's hot. The radar tells you what to adopt — and
> what it takes to run it.

## 2. Principles

- **Rendering over new pipelines.** Every feature below reads data the radar
  already persists (`history.jsonl`, `trending-observations.jsonl`,
  `model-metrics.jsonl`, per-project metrics, evidence). No new collectors.
- **Placement cannot be bought.** No sponsored slots, ever. The contrast with
  trendshift's paid "Featured" placement is part of the brand: rings are
  computed, auditable, append-only.
- **Static-site parity.** Everything works identically on the dashboard and
  the exported static site: no JS chart libraries, no external assets.
  Sparklines and badges are inline/self-contained SVG generated
  deterministically at render/export time.
- **Effective history only.** Tenure/credential lines compute over the
  corrected (effective) timeline from sub-project A — outage artifacts and
  their corrections never inflate a credential.
- Deterministic core, WCAG AA contrast per the shared design system, Mega
  brand tokens. Accessibility: sparklines carry `aria-label` text
  equivalents; badges carry `<title>`.

## 3. Features

### F1 — Tenure credential line ("the résumé")

One line on every tool card and project page, and every model card/page:

> `On radar 312 days · ADOPT since 2026-05-12 · 2 ring changes`

- Source: effective ring timeline (`apply_corrections`) — first_seen, current
  ring's earliest continuous start, effective change count.
- "ADOPT since" = the observed_at of the earliest event of the current
  unbroken ring streak (walk effective events backward while ring is equal).
- Models use the model-history log equivalently.
- Rendered as muted text under the ring pill; identical on static export.

### F2 — Sparklines

Tiny inline SVG series (last 14 observations, no axes, single brand-colored
polyline + endpoint dot), on:

- `/trending` rows: star count series per repo from
  `trending-observations.jsonl`.
- Model rows/pages: weekly-download series from `model-metrics.jsonl`.
- Project pages: star history from per-scan project metrics (where ≥3 points).

Implementation: one pure helper `sparkline_svg(values: list[float], *,
label: str) -> str` (markupsafe-escaped, fixed 120×28 viewBox, `<title>` +
`aria-label`), unit-tested for determinism and empty/one-point series
(render nothing below 3 points).

### F3 — Time-window tabs on /trending

`7d` (default) · `30d` · `90d` tabs replacing nothing — lanes stay; tabs set
the velocity window used for ranking, computed from the observation log
(windows the log can actually support; trendshift's "daily" resolution is
not honestly available from a once-daily sweep, so we do not fake it).
Static export renders three pre-computed variants
(`trending.html`, `trending-30d.html`, `trending-90d.html`) with tab links;
dashboard uses a query param. Momentum badges (NEW/STALE) unchanged.

### F4 — Badges (the growth loop, carrying a verdict)

Embeddable, self-contained SVG badges, generated at export time into
`_site/badges/` and served by the dashboard at `/badge/...`:

- **Ring badge** per tracked project: `on-prem radar | ADOPT` in ring color
  (`badges/<project-slug>.svg`).
- **Model ring badge** per model: same shape (`badges/model-<id>.svg`).
- **Fit badge** per model: `runs on | workstation (Q5)` from the existing
  hardware_tier + min-viable quant (`badges/fit-<id>.svg`). GPU-count badges
  arrive with sub-project D — the URL scheme must not need to change
  (query-free, path-only).
- Every project/model detail page gets a "Badge" section: badge preview +
  copy-ready Markdown snippet linking back to the page's canonical static URL.
- SVG is hand-templated (shields.io-style two-cell pill), deterministic,
  no external fonts (system font stack), ring colors from the design tokens
  with AA-checked text contrast.
- Badges are rendered from the latest *published* data at export time; the
  dashboard route reads the DB. A project with a pinned override renders the
  pinned ring (pins win everywhere else; badges are no exception).

### F5 — Receipts-first cards

Index/tool cards lead with evidence, not just the ring pill:

- Up to two headline evidence lines already computed per card (advisory
  status, license stability, release cadence, momentum) rendered under the
  summary — the "why" visible without a click.
- HN mentions strip: `12 HN mentions this week` chip when
  `hn_mentions > 0` in the latest metrics (data already collected by
  enrichment; currently buried).

### F6 — Positioning copy

- Site hero subtitle and README top section adopt the positioning line and a
  three-bullet "how we differ" block (computed rings vs paid placement ·
  every number cited · queryable by agents over MCP).
- The weekly digest gains the same one-liner in its header.

## 4. Non-goals

- Reddit/X mention scraping (HN only — already collected).
- Any paid/sponsored placement mechanics.
- Daily-resolution trending (the sweep is daily; sub-daily windows would be
  fake precision).
- GPU-count fit badges (needs sub-project D's capacity engine; URL scheme is
  forward-compatible).
- JSON data API (sub-project F).
- Trending-archive page ("every repo that ever trended") — our equivalent is
  the existing per-project timeline; F1 surfaces it.

## 5. Decomposition

Single sub-project ("DP"), one plan, ~6 tasks expected: (1) tenure
credential helpers + card/page rendering, (2) sparkline helper + trending
wiring, (3) model/project sparkline wiring, (4) time-window tabs, (5) badge
generator + pages + export/routes, (6) receipts-first cards + HN chip +
positioning copy. Standard flow: plan → subagent-driven execution →
whole-branch review → PR with checks verified green before merge.

## 6. Testing

- Pure helpers (tenure computation, sparkline SVG, badge SVG) golden-tested
  for determinism; property: sparkline never emits NaN coordinates; badge
  text contrast asserted against ring token colors.
- Static/dashboard parity tests per surface (existing pattern).
- Effective-history invariant: a project with corrected outage events shows
  tenure identical to its artifact-free twin (regression vs sub-project A).
- Backward compat: cards without metrics/history render without the new
  elements (no empty chrome).
