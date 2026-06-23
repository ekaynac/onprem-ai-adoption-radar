# Catalog Growth on Autopilot — weekly auto-promotion of discovered models

## Context

The local-model catalog (`config/model-seed.yaml`, now 33 models) grows by hand: a person runs
`radar models discover` (writes trending HF candidates to the gitignored `data/proposed-model-seeds.yaml`)
and manually transcribes good ones into the seed file. Discovery is **not wired into CI** and there is **no
promotion mechanism** — proposals carry only trending metadata (downloads/likes/repo), no specs.

**Goal (user-chosen):** fully hands-off autopilot — a **weekly** CI job that discovers trending models,
enriches them into complete seed entries, and **auto-commits** them to `config/model-seed.yaml` (no PR /
human gate). The daily `publish.yml` then republishes the site.

**Consequence — the safety net moves into code.** Today the project's stated principle is "never auto-adds"
(human review is the quality gate). Auto-commit removes that gate, so the *only* thing preventing catalog
pollution (GGUF dumps, finetunes, broken specs, duplicate ids) is **conservative automated filtering +
mandatory spec-enrichment + validate-or-abort**. This plan invests heavily there. (This intentionally
reverses the "never auto-adds" docstring in `discovery/model_proposals.py`, which will be updated.)

## Design overview

Weekly GitHub Actions job → `radar models discover` (refresh proposals) → **`radar models promote`** (new:
filter → enrich → append → validate) → commit `config/model-seed.yaml` to `main` → trigger `publish.yml`.

The new work is one module + one CLI command + one workflow. Everything reuses existing pieces:
`discover_trending_models` (`discovery/hf_trending_models.py`), `load_model_proposals`/`ModelProposal`
(`discovery/model_proposals.py`), `fetch_hf_model`/`HFModelData` (`models_radar/collectors/huggingface.py`),
`openness_from_license` (`models_radar/assemble.py`), `load_model_seed`/`ModelSeedError`
(`models_radar/seed.py`), `ModelSeed` (`models_radar/entities.py`), `Backer`/`BackerType` (`models.py`).

### The safety net (no human gate → these rules are the gate)

A proposal is promoted **only if all** hold (anything else → skipped, logged):
- **Not already seeded** — dedup by `hf_repo` (case-insensitive) AND generated `id`.
- **Download floor** — `downloads >= --min-downloads` (default **100_000**, higher than discover's 10k).
- **Not a derivative/quant repo** — repo name/path matches none of a denylist regex:
  `gguf|awq|gptq|exl2|-bnb|fp8|int4|int8|-4bit|-8bit|-mlx|-quantized|-lora|-adapter`.
- **Not a known republisher org** — HF org not in a denylist: `TheBloke, unsloth, bartowski,
  mradermacher, QuantFactory, lmstudio-community, second-state, RichardErkhov, DevQuasar`.
- **Generative text/multimodal only** — modality in `{text, multimodal}` (skip pure audio/image/embeddings).
- **Specs fetch succeeds with real params** — `fetch_hf_model(hf_repo)` returns non-None AND `params_total`
  is present. A model we can't size is useless for the "what can I run" radar → skip.
- **Per-run cap** — at most `--limit` promotions (default **5**) so a single week can't flood the catalog.

### Enrichment (proposal → complete ModelSeed)

For each surviving candidate, build a `ModelSeed`:
- `id` = proposal `suggested_id` (`hf-<slug>`); if it collides with an existing id, append `-2`, `-3`… or skip.
- `name` = proposal `name`; `hf_repo` = proposal `hf_repo`; `modality` from proposal.
- `family` = best-effort from the model name (strip trailing size/variant, e.g. `Qwen3-0.6B`→`Qwen3`); falls
  back to the proposal family (org). Imperfect but acceptable for autopilot; a human can refine later.
- `params_total`, `num_layers`, `hidden_size`, `context_length`, `license` from `fetch_hf_model`.
- `openness` = `openness_from_license(license)`.
- `release_date` = `HFModelData.last_modified` truncated to `YYYY-MM` (HF has no true release date; this is the
  documented approximation).
- `backer` = lookup of the HF org in a curated `_ORG_BACKER` map (Qwen→Alibaba/big_tech, meta-llama→Meta,
  mistralai→Mistral AI/startup, google→Google, microsoft→Microsoft, deepseek-ai→DeepSeek/startup,
  CohereForAI/CohereLabs→Cohere/startup, 01-ai→01.AI/startup, ibm-granite→IBM, HuggingFaceTB→Hugging Face/
  community, bigcode→BigCode/community, nvidia→NVIDIA, allenai→AllenAI/academic, …); fallback
  `{name: <org>, type: community}`.
- Left null for later human refinement: `ollama_name`, `params_active` (MoE not auto-detected — note it),
  `use_case`. These being null is harmless (the radar degrades gracefully).

### Validate-or-abort append

Render each new seed as a YAML **text block** matching the file's hand-authored style (2-space indent,
`- id:` list form, inline `backer: {name: "...", type: ...}`) and **append** to `config/model-seed.yaml`
(never re-dump the whole file — that would destroy comments + reformat). Then: write to a temp copy, run
`load_model_seed(temp)` + assert ids are unique; **only replace the real file if validation passes**,
otherwise discard and exit non-zero. This guarantees CI never commits a broken catalog.

---

## Tasks

### Task 1 — Promotion module (`src/radar/discovery/model_promotion.py`, new)
Pure, testable logic (no I/O beyond the HF client passed in):
- `_ORG_BACKER: dict[str, Backer]` curated map (above) + `backer_for_org(org) -> Backer` (fallback community).
- `_DERIVATIVE_RE` + `_REPUBLISHER_ORGS` + `is_promotable(proposal, *, min_downloads, seeded_repos) -> bool`.
- `derive_family(name: str) -> str` (strip trailing size/variant token).
- `async def build_seed(proposal, hf, *, existing_ids) -> ModelSeed | None` — assemble the enriched
  `ModelSeed` from a proposal + its `HFModelData` (None if no `params_total` or id can't be made unique).
- `seed_to_yaml_block(seed: ModelSeed) -> str` — render the seed as a config-style YAML block.
Tests (`tests/test_model_promotion.py`): filtering rejects gguf/republisher/low-download/seeded; backer map +
fallback; family derivation; `build_seed` fills specs/openness/release_date and skips no-params; the rendered
block re-parses via `load_model_seed` into an equal seed.

### Task 2 — `radar models promote` CLI (`src/radar/cli.py`, extend `models_app`)
`radar models promote [--limit 5] [--min-downloads 100000] [--dry-run] [--root .]`:
load proposals (`load_model_proposals`) + existing seeds; filter via `is_promotable`; for each (up to limit)
`fetch_hf_model` → `build_seed`; append rendered blocks to `config/model-seed.yaml` with the validate-or-abort
temp swap; print a table of what was added (or, with `--dry-run`, what *would* be added — no write). Exit
non-zero if the post-append catalog fails to load. Test mirrors `tests/test_models_radar_cli.py` (monkeypatch
the HF client + a temp proposals file + temp seed file; assert new entries land and the file still loads;
assert `--dry-run` writes nothing).

### Task 3 — Weekly autopilot workflow (`.github/workflows/catalog-autopilot.yml`, new)
```yaml
on:
  schedule: [{ cron: "0 7 * * 1" }]   # Mondays 07:00 UTC
  workflow_dispatch: {}
permissions: { contents: write, actions: write }
```
Steps: checkout → install (uv, mirror `publish.yml`) → `radar models discover --root .` →
`radar models promote --root . --limit 5` (env `GITHUB_TOKEN`/`HF_TOKEN` if available) → **gate**
`uv run pytest tests/test_models_radar_seed.py -q` (catalog still valid) → if `config/model-seed.yaml`
changed, `git add config/model-seed.yaml && git commit -m "chore(catalog): autopilot add <ids>" && git push`
→ `gh workflow run publish.yml` to republish (default `GITHUB_TOKEN` pushes don't auto-trigger other
workflows; the explicit dispatch makes the site update immediately rather than waiting for the daily run).
Guard every commit behind "did the file change AND did the gate pass".

### Task 4 — Docs + principle update + gate + live smoke + merge
- Update the `discovery/model_proposals.py` module docstring (and any README/docs note) to reflect that model
  discovery now has an **opt-in auto-promotion path** (weekly CI), while manual review remains available.
- Full gate (ruff + mypy + pytest) green.
- Live smoke (no commit): `radar models discover --root .` then `radar models promote --root . --dry-run`
  on the real catalog → prints sane enriched candidates, skips gguf/republisher/seeded, writes nothing.
  Then a real `--limit 1` run in a throwaway copy → `config/model-seed.yaml` still loads + ids unique.
- Final review; `--no-ff` merge to `main`; push (integrate CI history first).

---

## Key files
- New: `src/radar/discovery/model_promotion.py`, `tests/test_model_promotion.py`,
  `.github/workflows/catalog-autopilot.yml`.
- Modify: `src/radar/cli.py` (`models_app` + `promote`), `src/radar/discovery/model_proposals.py` (docstring),
  `tests/test_models_radar_cli.py` (promote test). Append target: `config/model-seed.yaml`.
- Reuse (unchanged): `discovery/hf_trending_models.py`, `models_radar/collectors/huggingface.py`
  (`fetch_hf_model`), `models_radar/assemble.py` (`openness_from_license`), `models_radar/seed.py`
  (`load_model_seed`), `models_radar/entities.py` (`ModelSeed`), `models.py` (`Backer`/`BackerType`).

## Global constraints
- Python ≥ 3.12; new modules begin with `from __future__ import annotations`; no new third-party deps;
  deterministic core, no LLM. `ModelSeed`/`Backer` stay frozen/strict (`extra="forbid"`). ruff + mypy clean;
  coverage ≥ 80%; full gate before every commit; commit on the current branch only. Never re-dump the whole
  `config/model-seed.yaml` (append blocks only). Never commit a catalog that fails `load_model_seed`.

## Verification (end-to-end)
1. Gates: `ruff check src tests`, `mypy src`, `pytest -q` green.
2. Unit: `tests/test_model_promotion.py` — filtering, backer map, family derivation, build_seed enrichment,
   round-trip (rendered block re-parses to an equal seed); `radar models promote` CLI test.
3. Local dry-run on the real catalog: `radar models discover` → `radar models promote --dry-run` prints
   enriched candidates and rejects gguf/republisher/seeded/low-download; **no file change**. A `--limit 1`
   real run on a copied tree leaves `config/model-seed.yaml` loading cleanly with unique ids.
4. Workflow: `act`/manual `workflow_dispatch` (or a careful read) confirms the gate-before-commit guard and
   that nothing commits when no new model qualifies.
5. Safety: confirm a seeded repo, a `*-gguf` repo, a `TheBloke/*` repo, and a specs-less repo are all skipped.
6. Final whole-branch review; merge to `main`; push.

## Out of scope
- **GPU/device autopilot.** GPUs aren't on any discovery API (not HF), so `DEVICE_PRESETS` stays manually
  curated — add new cards by hand as they launch (cheap, infrequent). No automation source exists.
- **PR-based review gate** (the user chose auto-commit). The `--dry-run` flag + the daily publish lag are the
  only review surface; the filtering rules are the quality gate.
- Per-model quality scoring beyond the filters (e.g. benchmark gating) and tok/s speed estimates.
