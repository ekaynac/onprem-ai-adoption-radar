# Trending Radar — Plan E (Adopt Card + Polish) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Close spec §4's one remaining item — a third social card for repos/models/techniques that reached the **adopt** ring this week — and land two deferred review polish items (webhook idempotence on manual reruns; a card-layout constant comment).

**Architecture:** Extend the existing pure `web/cards.py` with an adopt-ring card derived from the digest's already-windowed `changes`; gate its emission in `write_cards` like the movers card. Make the digest CLI fire the webhook only when the ISO-week label is newly logged (a `workflow_dispatch` re-run of the same week no longer re-pings subscribers).

**Tech Stack:** Python 3.12, pytest + ruff + mypy. **No new dependencies.**

**Spec:** `docs/superpowers/specs/2026-07-05-trending-radar-design.md` §4 (the "new adopt-ring entries" card, listed there, previously simplified out).

## Global Constraints

- Deterministic pure cards (SVG strings); brand-kit constraint unchanged (Process Blue `#009FDA` + text wordmark + font stack only — NO brand asset).
- ruff line-length 100; `from __future__ import annotations`; coverage ≥ 80%; gates `uv run pytest`, `uv run ruff check .`, `uv run mypy src/radar`.
- Commit format `<type>: <description>`; `git add` specific paths only (unrelated modified `data/history.jsonl` never committed; `digests/` generated output is not source — do not commit generated artifacts).
- Consumed symbols (on main): `WeeklyDigest`/`DigestChange` (`radar.reports.digest`), `render_card`/`write_cards`/`CARD_SIZES` (`radar.web.cards`), `send_digest_notification` (`radar.notify.webhook`), `load_digests`/`append_digest`/`DigestLogEntry` (`radar.storage.digest_log`). Ring values are `adopt|pilot|watch|avoid`; ChangeType `new|promoted|demoted|updated`.

## File Structure

```
src/radar/web/cards.py            # MODIFY: _adopt_rows + write_cards emits an adopt card; band comment
src/radar/cli.py                   # MODIFY: digest generate fires webhook only when label newly logged
tests/test_social_cards.py         # MODIFY: adopt-card emission + skip-when-none
tests/test_digest_cli.py           # MODIFY: webhook fires once across two same-week runs
CHANGELOG.md                        # MODIFY
```

---

### Task 1: Adopt-ring social card

**Files:**
- Modify: `src/radar/web/cards.py`
- Test: `tests/test_social_cards.py`

**Interfaces:**
- Consumes: `WeeklyDigest`/`DigestChange`, `render_card`, `CARD_SIZES`.
- Produces: `_adopt_rows(digest) -> list[str]` (up to 3 rows for changes that ENTERED the adopt ring this week: `c.ring == "adopt" and c.change_type in {"new", "promoted"}`, formatted `"{name}  ({kind})"`); `write_cards` appends an `("adopt", f"Reached adopt · {label}", rows)` spec (both sizes) when `_adopt_rows` is non-empty.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_social_cards.py` (reuse the file's existing `_digest`, `DigestChange`, `datetime`/`UTC` imports; `_digest()` already contains one adopt-ring change):

```python
def test_write_cards_emits_adopt_card_for_adopt_entries(tmp_path):
    # _digest()'s change is promoted → adopt this week, so an adopt card is emitted.
    names = {p.name for p in write_cards(_digest(), tmp_path)}
    assert "adopt_portrait.svg" in names and "adopt_og.svg" in names
    page = (tmp_path / "adopt_portrait.svg").read_text(encoding="utf-8")
    assert "Reached adopt" in page and "Cline" in page


def test_write_cards_skips_adopt_card_when_no_adopt_entries(tmp_path):
    from radar.reports.digest import DigestChange as _DC

    # a change that does NOT reach adopt (pilot ring) → no adopt card
    non_adopt = _DC(kind="tool", name="X", change_type="promoted", ring="pilot",
                    previous_ring="watch", observed_at=datetime(2026, 7, 7, tzinfo=UTC))
    d = _digest().model_copy(update={"changes": [non_adopt]})

    names = {p.name for p in write_cards(d, tmp_path)}
    assert not any("adopt" in n for n in names)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_social_cards.py -v -k adopt`
Expected: FAIL — no `adopt_*.svg` written

- [ ] **Step 3: Implement**

In `src/radar/web/cards.py`, add after `_mover_rows`:

```python
def _adopt_rows(digest: WeeklyDigest) -> list[str]:
    """Up to 3 entries that reached the adopt ring this week (across all radars)."""
    rows = []
    for c in digest.changes:
        if c.ring == "adopt" and c.change_type in {"new", "promoted"}:
            rows.append(f"{c.name}  ({c.kind})")
        if len(rows) >= 3:
            break
    return rows
```

In `write_cards`, after the movers append:

```python
    adopt = _adopt_rows(digest)
    if adopt:
        specs.append(("adopt", f"Reached adopt · {digest.label}", adopt))
```

Also add a one-line comment on the `band` constant in `render_card` (the remaining uncommented magic number): `band = max(120, height // 8)  # brand header band height (min 120px)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_social_cards.py -v`
Expected: PASS (existing + 2 new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/web/cards.py tests/test_social_cards.py && uv run mypy src/radar
git add src/radar/web/cards.py tests/test_social_cards.py
git commit -m "feat: adopt-ring social card (spec §4's third card)"
```

---

### Task 2: Webhook idempotence on same-week reruns

**Files:**
- Modify: `src/radar/cli.py`
- Test: `tests/test_digest_cli.py`

**Interfaces:**
- The digest command already dedups the log append by ISO-week label (`existing_labels`, only appends when the label is absent). Extend that: capture `label_is_new = digest.label not in existing_labels`, gate BOTH the append AND the webhook fire on `label_is_new`. A `workflow_dispatch` re-run of an already-generated week rewrites artifacts but does NOT re-ping subscribers.
- Make the webhook call monkeypatch-friendly: call it as a module attribute (`from radar.notify import webhook` then `webhook.send_digest_notification(...)`), so the test can patch `radar.notify.webhook.send_digest_notification` and count invocations.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_digest_cli.py` (reuse its existing `_seed_trending` + CliRunner):

```python
def test_digest_webhook_fires_once_per_week(tmp_path, monkeypatch):
    _seed_trending(tmp_path)
    # enable notify so the webhook path is live
    (tmp_path / "data" / "config.yaml").write_text(
        "sources: []\nnotify:\n  enabled: true\n  webhook_url: https://example.test/hook\n",
        encoding="utf-8",
    )
    calls = []

    async def _fake_send(config, digest, client):
        calls.append(digest.label)
        return True

    monkeypatch.setattr("radar.notify.webhook.send_digest_notification", _fake_send)
    runner = CliRunner()

    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])
    runner.invoke(app, ["digest", "generate", "--root", str(tmp_path)])  # same ISO week

    assert len(calls) == 1   # first run pings; second run (same week) does not re-ping
```

NOTE for the implementer: confirm the minimal `config.yaml` above load-validates against the real `Config`/`NotifyConfig` schema (extra="forbid" on both); if `sources: []` or the notify shape needs adjusting to parse, fix the fixture to the real schema — the assertion (`len(calls) == 1`) is the contract. If the digest command currently imports `send_digest_notification` by name, switch it to the module-attribute call so the monkeypatch target resolves.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_digest_cli.py -v -k webhook_fires_once`
Expected: FAIL — webhook fires twice (once per run)

- [ ] **Step 3: Implement**

In `src/radar/cli.py`'s `digest generate`, replace the append-gating block so `label_is_new` is captured and reused, and gate the webhook on it. Current:

```python
    existing_labels = {e.label for e in load_digests(log_path)}
    ...
    if digest.label not in existing_labels:
        append_digest(log_path, [DigestLogEntry(...)])
    ...
    try:
        asyncio.run(_notify())
    except Exception as exc:
        console.print(f"[yellow]Digest webhook failed: {exc}[/yellow]")
```

becomes:

```python
    existing_labels = {e.label for e in load_digests(log_path)}
    label_is_new = digest.label not in existing_labels
    ...
    if label_is_new:
        append_digest(log_path, [DigestLogEntry(...)])
    ...
    # Fire the webhook only for a newly-logged week — a manual re-run of the same
    # ISO week rewrites artifacts but must not re-ping subscribers.
    if label_is_new:
        try:
            asyncio.run(_notify())
        except Exception as exc:
            console.print(f"[yellow]Digest webhook failed: {exc}[/yellow]")
```

and inside `_notify()` call `webhook.send_digest_notification(...)` via the module import (add `from radar.notify import webhook` in the command's imports; keep any existing `NotifyConfig` import).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_digest_cli.py -v`
Expected: PASS (existing + new)

- [ ] **Step 5: Lint + typecheck + commit**

```bash
uv run ruff check src/radar/cli.py tests/test_digest_cli.py && uv run mypy src/radar
git add src/radar/cli.py tests/test_digest_cli.py
git commit -m "fix: digest webhook fires once per ISO week (no re-ping on rerun)"
```

---

### Task 3: CHANGELOG + full gates

**Files:**
- Modify: `CHANGELOG.md`
- Test: the full suite

- [ ] **Step 1: CHANGELOG**

Under `## [Unreleased]` → `### Added` (or a `### Changed`/`### Fixed` as fits), add:

```markdown
- **Adopt-ring social card** — the weekly digest now emits a third Mega-branded
  card for repos/models/techniques that reached the **adopt** ring during the
  week (completing spec §4's card set); the digest webhook fires once per ISO
  week (a manual re-run no longer re-pings subscribers).
```

- [ ] **Step 2: Full gates**

Run: `uv run pytest && uv run ruff check . && uv run mypy src/radar`
Expected: all pass, coverage ≥ 80%, ruff + mypy clean.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: adopt-ring card + webhook idempotence in CHANGELOG"
```

---

## Self-Review Notes (already applied)

- Spec §4's third card ("new adopt-ring entries") now shipped (T1); the two deferred review minors — webhook re-fire on manual reruns (T2) and the uncommented `band` constant (T1) — closed. The other deferred minor (feed-URL freeze on relabel) is intentionally left: CI always passes `--base-url`, so the first-write URL is already absolute.
- Determinism/brand: the adopt card reuses the pure `render_card` (no brand asset); the webhook change only reorders a guard.
- Type consistency: `_adopt_rows(digest)` mirrors `_mover_rows`; `write_cards`'s spec tuple shape unchanged; `label_is_new` reuses the existing `existing_labels` set.
