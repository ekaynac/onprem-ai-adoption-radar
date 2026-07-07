# Data-Quality Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the six audit findings: the rising/steady momentum mislabel, noise-prone citation thresholds, the stale ring-event override, the Ornith params bug + an autopilot plausibility guard, silent-stale export renders, and the never-shown momentum note.

**Architecture:** Five small pure-function/seed/template fixes plus one export guard. All detection/momentum stays pure (`now` a parameter; only CLI/MCP boundaries read the clock). No storage-format or gateway changes.

**Tech Stack:** Python 3.12, pydantic v2, Jinja2, typer (in-tree; **no new dependencies**), pytest + ruff + mypy.

**Spec:** `docs/superpowers/specs/2026-07-07-data-quality-fixes-design.md`. Audit evidence: `.superpowers/sdd/dq-findings.md`.

## Global Constraints

- Pure functions take `now`; only CLIs/MCP query boundaries read `datetime.now(UTC)`.
- Guarded gateways and committed-log formats UNTOUCHED. Failure in any new guard degrades to today's behavior — never crashes a scan or export (daily-publish invariant).
- Constants (spec-decided): `RISING_MOMENTUM = 4`; `CITATION_BASELINE_FLOOR = 50`; `CITATION_FALLING_PCT = -2.0` (falling iff growth < −2.0); `RING_EVENT_WINDOW_DAYS = 30`; params guard tolerance **5×**.
- Datetime windows compare **`.date()` values** (naive/aware-proof — `ModelHistoryEvent.observed_at` has no tz validator; this is the recurring crash class).
- **PLAN-TIME CORRECTION to spec fix #5** (mechanism, not intent): the export renders the latest research run's `technique_cards.json` snapshot (`mcp_server/technique_queries.py::_latest_technique_cards`); NO render path reads `TechniqueMetricsStore`, and the scan CLI already passes `metrics_log_path` (cli.py:593) so scan-time rehydration works. Rehydrating the store at export would be a no-op. Task 6 therefore delivers the intent as: (a) a regression test pinning the scan CLI's `metrics_log_path` threading, (b) an export-time staleness warning when the latest research run is missing or older than `EXPORT_RESEARCH_STALE_DAYS = 2`.
- ruff line-length 100 (E501 ignored); `from __future__ import annotations`; coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit `<type>: <description>`; `git add` specific paths only (`data/history.jsonl` never committed).

## Existing code being modified (verified on branch)

- `src/radar/research_radar/momentum.py`: `CITATION_RISING_PCT = 10.0`; `momentum_signal(technique_id, previous_rows, citation_count, citation_source, impl_count)` — falling branch fires on any `growth < 0` (line 52) and `falling_too = growth is not None and growth < 0` (line 45); `_citation_growth_pct(rows, current, source)` returns pct vs most recent same-source row (line 68-79).
- `src/radar/web/hub_sections.py:29` `RISING_MOMENTUM = 3`; line 115 `direction = "rising" if mom >= RISING_MOMENTUM else "falling" if mom <= 2 else "steady"`; line 124 rising filter `_momentum(e) >= RISING_MOMENTUM`.
- `src/radar/models_radar/momentum.py`: `RECENT_EVENTS = 3`; `compute_model_momentum(model_id, metric_rows, ring_events)` — lines 38-46 scan `ring_events[-RECENT_EVENTS:]` with no time bound. Callers: `models_radar/pipeline.py:86` (inside its momentum loader), `web/hub_sections.py:82` (`now` in scope), `mcp_server/model_queries.py:82,133`, `tests/test_models_radar_momentum.py`.
- `src/radar/discovery/model_promotion.py:177` `build_seed(proposal, hf, *, existing_ids)` — line 190 returns None when `hf.params_total is None`; line 227 `params_total=hf.params_total`.
- `config/model-seed.yaml:498` `params_total: 664944` under `id: hf-ornith-1-0-35b`.
- `src/radar/research_radar/pipeline.py:60-78` `score_technique_entries` — `model_copy(update={"score": ..., "score_breakdown": ..., "ring": ...})` discards `MomentumSignal.note`/`.direction`.
- `src/radar/research_radar/entities.py:110` `TechniqueEntry` (has `notes`, no momentum note/direction fields).
- `src/radar/web/templates/_technique_detail.html` renders only the bare momentum integer.
- `src/radar/cli.py:583-595` research scan passes `metrics_log_path` (pin with a test); the `export` command near line 1613 loads `technique_entries = load_technique_entries(root)`.

## File Structure

```
src/radar/research_radar/momentum.py       # T1: floor + deadband
src/radar/web/hub_sections.py              # T2: RISING_MOMENTUM = 4
src/radar/models_radar/momentum.py         # T3: ring-event 30d window (+ now param)
src/radar/models_radar/pipeline.py cli.py mcp_server/model_queries.py  # T3: thread now
config/model-seed.yaml src/radar/discovery/model_promotion.py          # T4: seed fix + plausible_params
src/radar/research_radar/entities.py pipeline.py templates/_technique_detail.html  # T5: momentum note
src/radar/cli.py                           # T6: export staleness warning
tests/...                                   # per task
README.md CHANGELOG.md                      # T6
```

---

### Task 1: Citation floor + falling deadband (spec fix #2)

**Files:**
- Modify: `src/radar/research_radar/momentum.py`
- Test: `tests/test_research_momentum.py` (locate the existing momentum test file — `grep -rl "momentum_signal" tests/`; append there)

**Interfaces:**
- Produces: `CITATION_BASELINE_FLOOR = 50`, `CITATION_FALLING_PCT = -2.0`; `_citation_growth_pct` returns `None` when the comparable baseline row's `citation_count < CITATION_BASELINE_FLOOR`; `momentum_signal` marks "falling" only when `growth < CITATION_FALLING_PCT` (both the plain falling branch and the `falling_too` intensifier). Signature unchanged.

- [ ] **Step 1: Write the failing tests** (adapt the row-builder helper to the existing test file's — it constructs `TechniqueMetrics(technique_id=..., run_id=..., observed_at=..., citation_count=..., citation_source="s2", resolved_impls=...)`; read the file first):

```python
def test_low_baseline_growth_is_no_signal():  # kto case: 7 -> 11 (+57%) is index noise
    rows = [_metric("t", citation_count=7)]
    sig = momentum_signal("t", rows, citation_count=11, citation_source="s2", impl_count=0)
    assert sig.score == 3 and sig.direction == "steady"
    assert sig.citation_growth_pct is None   # floor: baseline < 50 -> no pct signal


def test_tiny_negative_delta_is_steady():  # self-consistency case: 7091 -> 7089 (-0.03%)
    rows = [_metric("t", citation_count=7091)]
    sig = momentum_signal("t", rows, citation_count=7089, citation_source="s2", impl_count=0)
    assert sig.direction == "steady" and sig.score == 3


def test_real_decline_still_falls():  # -3% on a large baseline crosses the deadband
    rows = [_metric("t", citation_count=1000)]
    sig = momentum_signal("t", rows, citation_count=970, citation_source="s2", impl_count=0)
    assert sig.direction == "falling" and sig.score == 2


def test_real_growth_still_rises():  # +12% on a baseline >= 50
    rows = [_metric("t", citation_count=1000)]
    sig = momentum_signal("t", rows, citation_count=1120, citation_source="s2", impl_count=0)
    assert sig.direction == "rising" and sig.score == 4
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/ -k "low_baseline or tiny_negative" -v`
Expected: FAIL — low-baseline reads rising(+57%), tiny-negative reads falling

- [ ] **Step 3: Implement**

In `momentum.py`, add under `CITATION_RISING_PCT`:

```python
CITATION_FALLING_PCT = -2.0   # noise deadband: only a real decline reads "falling"
CITATION_BASELINE_FLOOR = 50  # pct growth on tiny citation counts is index noise
```

In `_citation_growth_pct`, extend the baseline guard (line 76):

```python
        if not row.citation_count or row.citation_count < CITATION_BASELINE_FLOOR:
            return None  # zero/None/tiny baseline: pct growth is noise, not signal
```

In `momentum_signal`, replace both `growth < 0` comparisons:

```python
    if impl_delta is not None and impl_delta < 0:
        falling_too = growth is not None and growth < CITATION_FALLING_PCT
        ...
    if growth is not None and growth < CITATION_FALLING_PCT:
        ...  # falling branch, was: growth < 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ -k momentum -v` — new tests pass; fix any existing momentum test that asserted falling on a small negative delta (update its delta to cross −2%, keeping its intent).

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/research_radar/momentum.py && uv run mypy src/radar
git add src/radar/research_radar/momentum.py tests/<the test file>
git commit -m "fix: citation floor + falling deadband stop noise-driven momentum flips"
```

---

### Task 2: RISING_MOMENTUM = 4 (spec fix #1)

**Files:**
- Modify: `src/radar/web/hub_sections.py:29`
- Test: `tests/test_hub_sections.py`

**Interfaces:**
- Produces: `RISING_MOMENTUM = 4`. Momentum-3 techniques are `steady` and excluded from the rising set (line 115 + 124 logic unchanged — only the constant moves). Matches `momentum.py`'s canonical scale (3 = steady).

- [ ] **Step 1: Update the tests to pin the canonical scale.** In `tests/test_hub_sections.py::test_technique_section_ranks_high_momentum` (entries hot=5, warm=4, mid=3, cold=2 currently expect `["hot", "warm", "mid"]` with a comment "momentum 3+ counts as trending"): change to

```python
    # canonical scale (momentum.py): 5/4 = rising, 3 = steady, <=2 = falling
    assert [r.id for r in rows] == ["hot", "warm"]
    assert rows[0].momentum == 5 and rows[0].direction == "rising"
    assert rows[1].id == "warm" and rows[1].direction == "rising"
```

Add a regression test:

```python
def test_momentum_three_is_steady_not_rising():
    entries = [_tentry("mid", 3, 500)]
    assert build_technique_section(entries, [], NOW) == []   # steady-3: not in the section
```

Also grep tests for any other `RISING_MOMENTUM` / momentum-3-included assumption (`grep -rn "RISING_MOMENTUM\|3/5 rising" tests/ src/`) and update.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_hub_sections.py -v`
Expected: FAIL — mid (momentum 3) still included

- [ ] **Step 3: Implement** — `src/radar/web/hub_sections.py:29`: `RISING_MOMENTUM = 4` (update its comment to cite the canonical scale).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_hub_sections.py tests/test_web.py tests/test_static_site.py -q`
Expected: PASS (the technique hub renders new-this-week rows even when the rising set is empty — the Phase-1 empty-section guard tests keep passing).

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web/hub_sections.py tests/test_hub_sections.py && uv run mypy src/radar
git add src/radar/web/hub_sections.py tests/test_hub_sections.py
git commit -m "fix: RISING_MOMENTUM=4 — steady-3 techniques no longer labeled rising"
```

---

### Task 3: Ring events windowed to 30 days (spec fix #3)

**Files:**
- Modify: `src/radar/models_radar/momentum.py`, `src/radar/models_radar/pipeline.py`, `src/radar/web/hub_sections.py`, `src/radar/mcp_server/model_queries.py`, `src/radar/cli.py` (if a CLI calls the pipeline loader without a `now`)
- Test: `tests/test_models_radar_momentum.py` (+ callers' tests)

**Interfaces:**
- Produces: `RING_EVENT_WINDOW_DAYS = 30`; `compute_model_momentum(model_id, metric_rows, ring_events, now)` — only ring events with `event.observed_at.date() >= (now - timedelta(days=RING_EVENT_WINDOW_DAYS)).date()` act as direction overrides; older events fall through to downloads growth. **`.date()` comparison** (naive/aware-proof). Every caller passes `now`: the models pipeline momentum loader gains a `now` parameter threaded from its callers; `hub_sections.py:82` passes its in-scope `now`; `model_queries.py:82,133` read `datetime.now(UTC)` at the MCP boundary.

- [ ] **Step 1: Write the failing tests** (mirror the file's `_row`/`_event` helpers + fixture dates):

```python
def test_old_demotion_no_longer_forces_falling():
    now = datetime(2026, 7, 8, tzinfo=UTC)
    ev = _event(change=ChangeType.DEMOTED, day=1, month=5)  # ~2 months old
    rows = [_row(100, 1), _row(100, 6)]                      # flat downloads
    m = compute_model_momentum("m", rows, [ev], now)
    assert m.direction == "steady"                           # stale event ignored


def test_recent_demotion_still_falls():
    now = datetime(2026, 7, 8, tzinfo=UTC)
    ev = _event(change=ChangeType.DEMOTED, day=5, month=7)   # 3 days old
    m = compute_model_momentum("m", [_row(100, 1)], [ev], now)
    assert m.direction == "falling"
```

Update every existing call in `tests/test_models_radar_momentum.py` to pass a `now` consistent with its fixture dates.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_models_radar_momentum.py -v` → TypeError (missing `now`).

- [ ] **Step 3: Implement** in `models_radar/momentum.py` (import `datetime`, `timedelta` from datetime):

```python
RING_EVENT_WINDOW_DAYS = 30  # older ring events stop overriding the downloads signal


def compute_model_momentum(
    model_id: str,
    metric_rows: list[ModelMetrics],
    ring_events: list[ModelHistoryEvent],
    now: datetime,
) -> ModelMomentum:
    """Direction of travel (rows + events oldest-first)."""
    growth = _downloads_growth_pct(metric_rows)
    cutoff = (now - timedelta(days=RING_EVENT_WINDOW_DAYS)).date()
    recent_events = [e for e in ring_events[-RECENT_EVENTS:] if e.observed_at.date() >= cutoff]
    for event in reversed(recent_events):
        ...  # PROMOTED/DEMOTED branches unchanged
```

- [ ] **Step 4: Thread `now` through every caller.** `grep -rn "compute_model_momentum" src tests` and update each: the loader in `models_radar/pipeline.py` (~line 80) gains `now: datetime` and passes it (then thread from ITS callers — grep the loader's name; CLI callers use their existing `now = datetime.now(UTC)` or add one); `web/hub_sections.py:82` passes the `now` already in scope; `mcp_server/model_queries.py:82,133` add `now=datetime.now(UTC)` locally (MCP = boundary). Update any caller test fixtures (re-date relative to the passed `now` where they seed absolute dates — the TR4/TR5 pattern).

- [ ] **Step 5: Run tests** — `uv run pytest tests/test_models_radar_momentum.py tests/test_hub_sections.py -q` plus the full suite `uv run pytest -q`. Expected: PASS.

- [ ] **Step 6: Lint + typecheck + commit**

```bash
uv run ruff check src/radar && uv run mypy src/radar
git add src/radar/models_radar/momentum.py src/radar/models_radar/pipeline.py \
  src/radar/web/hub_sections.py src/radar/mcp_server/model_queries.py src/radar/cli.py \
  tests/test_models_radar_momentum.py <other updated test files>
git commit -m "fix: ring events older than 30 days stop forcing model momentum"
```

---

### Task 4: Ornith params fix + plausibility guard (spec fix #4)

**Files:**
- Modify: `config/model-seed.yaml:498`, `src/radar/discovery/model_promotion.py`
- Test: `tests/test_model_promotion.py` (append), `tests/test_models_radar_cli.py` or a seed-validation test file (locate `grep -rl "load_model_seed" tests/` for where seed sanity tests live)

**Interfaces:**
- Produces: `plausible_params(name: str, params_total: int | None) -> int | None` (pure, in `model_promotion.py`) — parses a leading size token `<N>B`/`<N>b` from the name; returns `params_total` unchanged when no token parses, the name matches MoE `AxB` (`\d+x\d+[bB]`), or `params_total` is None; returns `None` (+ `logger.warning`) when the value differs from `N × 1e9` by more than **5×** either way. `build_seed` runs `hf.params_total` through it BEFORE the line-190 None-check (an implausible value → seed skipped this round with a warning — better absent than seeding garbage fit-math; uncertain parses keep the value).
- `config/model-seed.yaml` Ornith entry: `params_total: 35000000000`.

- [ ] **Step 1: Write the failing tests**

```python
def test_plausible_params_rejects_ornith_class_error():
    assert plausible_params("Ornith-1.0-35B", 664944) is None          # ~52,000x off


def test_plausible_params_keeps_consistent_and_ambiguous_values():
    assert plausible_params("GLM-5.2", 753329940480) == 753329940480   # no size token -> keep
    assert plausible_params("Qwen3-32B", 32_800_000_000) == 32_800_000_000  # within 5x
    assert plausible_params("Mixtral-8x7B", 46_700_000_000) == 46_700_000_000  # MoE AxB -> skip
    assert plausible_params("SmolLM2-1.7B", 1_710_000_000) == 1_710_000_000   # sub-1B ok
    assert plausible_params("Some-35B", None) is None                   # None passes through


def test_seed_ornith_params_corrected():
    seeds = load_model_seed(Path("config/model-seed.yaml"))
    ornith = next(s for s in seeds if s.id == "hf-ornith-1-0-35b")
    assert ornith.params_total == 35_000_000_000
```

- [ ] **Step 2: Run to verify failure** — ImportError on `plausible_params`; seed assertion fails at 664944.

- [ ] **Step 3: Implement.** In `model_promotion.py`:

```python
_SIZE_TOKEN = re.compile(r"(\d+(?:\.\d+)?)\s*[bB]\b")
_MOE_TOKEN = re.compile(r"\d+x\d+(?:\.\d+)?\s*[bB]\b")
PARAMS_TOLERANCE = 5.0  # name says 35B but value differs by >5x either way -> implausible


def plausible_params(name: str, params_total: int | None) -> int | None:
    """params_total, or None (+ warning) when wildly inconsistent with the name's size token."""
    if params_total is None or _MOE_TOKEN.search(name):
        return params_total  # MoE AxB naming is total-vs-active ambiguous: never guess
    match = _SIZE_TOKEN.search(name)
    if not match:
        return params_total
    nominal = float(match.group(1)) * 1e9
    if params_total > nominal * PARAMS_TOLERANCE or params_total < nominal / PARAMS_TOLERANCE:
        logger.warning("Implausible params_total %d for %r (name suggests ~%.0f) — dropping",
                       params_total, name, nominal)
        return None
    return params_total
```

In `build_seed`, before the existing None-check (line ~190): `params = plausible_params(proposal.name, hf.params_total if hf else None)` and use `params` in place of `hf.params_total` in both the check and the seed construction (line 227). Correct `config/model-seed.yaml:498` to `params_total: 35000000000`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_model_promotion.py -v` + the seed test + `tests/test_models_radar_cli.py -q` (promote fixtures unaffected — their names/params are consistent). Expected: PASS.

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/discovery/model_promotion.py && uv run mypy src/radar
git add config/model-seed.yaml src/radar/discovery/model_promotion.py tests/<updated files>
git commit -m "fix: correct Ornith params_total; autopilot rejects implausible sizes"
```

---

### Task 5: Momentum note + direction on technique pages (spec fix #6)

**Files:**
- Modify: `src/radar/research_radar/entities.py` (`TechniqueEntry`), `src/radar/research_radar/pipeline.py` (`score_technique_entries`), `src/radar/web/templates/_technique_detail.html` (+ its static twin if the static export uses a separate partial — `grep -rln "technique_detail\|score_breakdown.momentum" src/radar/web/templates/`; apply the identical block)
- Test: `tests/test_web.py` or the technique-page test file (`grep -rl "technique_" tests/test_web.py tests/test_static_site.py`)

**Interfaces:**
- Produces: `TechniqueEntry.momentum_direction: str | None = None` + `TechniqueEntry.momentum_note: str | None = None` (optional — old `technique_cards.json` snapshots without them validate to None); `score_technique_entries` adds `"momentum_direction": momentum.direction, "momentum_note": momentum.note or None` to the `model_copy(update=...)`; the technique detail template renders them next to the momentum score (plain text — visual styling is sub-project 2):

```html
{% if technique.momentum_direction %}
<p class="momentum-note">Momentum: {{ technique.momentum_direction }}{% if technique.momentum_note %} — {{ technique.momentum_note }}{% endif %}</p>
{% endif %}
```

- [ ] **Step 1: Write the failing tests**

```python
def test_score_entries_carry_momentum_narrative():
    # build one entry + a prior metrics row producing a rising signal (reuse the
    # pipeline test file's fixtures); assert the scored entry carries the fields
    scored = score_technique_entries([entry], store)[0]
    assert scored.momentum_direction in {"rising", "falling", "steady"}
    assert scored.momentum_direction == "rising"
    assert "Citations" in (scored.momentum_note or "")


def test_technique_page_renders_momentum_note(tmp_path):
    # seed a technique_cards.json snapshot whose entry has momentum_direction/note
    # (reuse the existing technique-page web-test fixture), GET the page, assert:
    assert "Momentum: rising" in r.text
```

(Adapt fixture plumbing to the existing technique web tests — they already seed a run snapshot; the assertions are the contract. Also assert an entry WITHOUT the fields still renders — back-compat with old snapshots.)

- [ ] **Step 2: Run to verify failure** — AttributeError / missing text.

- [ ] **Step 3: Implement** the two entity fields, the `model_copy` update, and the template block (live + static twin byte-identical if separate).

- [ ] **Step 4: Run tests** — `uv run pytest tests/test_web.py tests/test_static_site.py -q` + the pipeline test file + full suite. Expected: PASS.

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar && uv run mypy src/radar
git add src/radar/research_radar/entities.py src/radar/research_radar/pipeline.py \
  src/radar/web/templates/ tests/<updated files>
git commit -m "feat: technique pages show the momentum direction + note"
```

---

### Task 6: Export staleness warning + rehydration pin + docs (spec fix #5, corrected)

**Files:**
- Modify: `src/radar/cli.py` (export), `README.md`, `CHANGELOG.md`
- Test: `tests/test_cli.py` (export warning + the scan-threading pin)

**Interfaces:**
- Produces: `EXPORT_RESEARCH_STALE_DAYS = 2` (in `cli.py` near the export command); at export time, after `technique_entries = load_technique_entries(root)`: if entries are empty, or the latest research run's meta timestamp is older than the threshold vs `generated_at`, print `console.print("[yellow]⚠ research data is stale/missing (latest research run ...); run `radar research scan` before export[/yellow]")` — warn-only, the export proceeds unchanged (daily-publish invariant). A regression test pins `metrics_log_path` in the research-scan CLI source (text-parse like the publish-workflow tests: assert `"metrics_log_path=root" in` the scan call region, or invoke the CLI with a stubbed `run_research_scan` capturing kwargs).

- [ ] **Step 1: Write the failing tests**

```python
def test_export_warns_when_research_snapshot_missing(tmp_path):
    # minimal exportable root WITHOUT any research run -> export succeeds but warns
    result = CliRunner().invoke(app, ["export", "--root", str(tmp_path), "--out",
                                      str(tmp_path / "_site")])
    assert result.exit_code == 0
    assert "research data is stale/missing" in result.output


def test_research_scan_threads_metrics_log(monkeypatch):
    captured = {}
    async def _fake_scan(**kwargs):
        captured.update(kwargs); return ([], [])
    monkeypatch.setattr("radar.research_radar.pipeline.run_research_scan", _fake_scan)
    # invoke `radar research scan --root <tmp>` with a valid minimal seed; then:
    assert captured["metrics_log_path"].name == "technique-metrics.jsonl"
```

(NOTE: check how cli.py imports run_research_scan — patch the name the CLI actually calls, e.g. `radar.cli.run_research_scan` if imported into the module, or the function-local import target. Adapt the export test's minimal-root plumbing to the existing export tests in test_cli.py; the contracts are: warning text present + exit 0, and metrics_log_path threaded.)

- [ ] **Step 2: Run to verify failure** — warning text absent.

- [ ] **Step 3: Implement** the warn-only staleness check in the export command (read the latest research run's meta via `RunStore` like `_latest_technique_cards` does, guarded `try/except → treat as missing`).

- [ ] **Step 4: Docs.** CHANGELOG `### Fixed` (top): one entry summarizing all six fixes (momentum mislabel `RISING_MOMENTUM=4`; citation floor 50 + −2% deadband; 30-day ring-event window; Ornith params + autopilot plausibility guard; export staleness warning; momentum note on technique pages). README: correct the test-count badge to the exact full-gate number.

- [ ] **Step 5: Full gates** — `uv run pytest && uv run ruff check . && uv run mypy src/radar`. Expected: green, coverage ≥ 80%.

- [ ] **Step 6: Commit**

```bash
git add src/radar/cli.py tests/test_cli.py README.md CHANGELOG.md
git commit -m "fix: export warns on stale research data; pin scan metrics-log threading; docs"
```

---

## Self-Review Notes (already applied)

- Spec coverage: fix #1→T2, #2→T1, #3→T3, #4→T4, #5→T6 (with the plan-time mechanism correction flagged in Global Constraints — the spec's store-rehydration-at-export would be a no-op since export renders the run snapshot and the scan already threads `metrics_log_path`), #6→T5.
- `now`-threading (T3) names every known caller + the grep to catch stragglers; `.date()` windows avoid the recurring naive/aware crash class.
- The T4 guard fails toward less data (drop value + warning); MoE `AxB` and token-less names are never second-guessed; the three ambiguous MoE seeds are NOT touched (spec: human review).
- Type consistency: `plausible_params(name, params_total) -> int | None`; `compute_model_momentum(..., now)`; `momentum_direction`/`momentum_note` optional on `TechniqueEntry` (snapshot back-compat); constants match the spec's decided values exactly.
