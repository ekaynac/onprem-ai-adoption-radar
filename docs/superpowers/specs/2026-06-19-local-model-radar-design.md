# Local-Model Radar — Design

Date: 2026-06-19
Status: approved (interactive brainstorm; both design batches confirmed)

## Context

The radar today tracks **tools/repos** (`SourceConfig` → `DecisionCard` with
adopt/pilot/watch rings and 7 tool-oriented score dimensions). Local **models**
(Llama, Qwen3 incl. MoE, DeepSeek, Mistral, gpt-oss, Gemma, Phi…) are a different
kind of artifact — parameters, quantizations, context length, modality, license,
memory footprint — and are not an entity in the system yet.

This sub-project adds a **local-model radar**: a spec-rich, catalog-first view of
notable locally-runnable models *with* a deterministic adoption recommendation,
reusing the existing radar's storage/history/momentum/web/MCP plumbing and shown
as a dedicated "Models" section alongside the tool categories. It is the second
of a planned sequence; **hardware-device matching** (LM-Studio-style "can *your*
machine run this?") is the next sub-project and consumes this catalog — so the
catalog must *capture* per-quantization memory footprints now, even though the
device-matching itself is out of scope here.

## Non-goals (this sub-project)

- No matching against a user's physical device specs (that is sub-project 3;
  this spec only produces the memory/hardware-tier data it will consume).
- No LLM in the default path; deterministic, identical inputs → identical output.
- No new third-party dependencies.
- Models do **not** flow through the existing 7-dimension tool `DecisionCard`;
  they get their own entity and scoring.

## Architecture (decided)

Parallel model entity, **shared infrastructure, unified dashboard**. Models reuse
the radar's storage/run/history/momentum/web/MCP plumbing but keep their own
spec-rich entity and model-specific scoring.

## 1. Entity & data model

New module `src/radar/models_radar/entities.py` (named to avoid clashing with the
existing `radar/models.py`):

- **`ModelEntry`** (frozen): `id` (slug), `name`, `family`, `backer` (reuse
  `Backer`), `hf_repo`, `ollama_name` (optional), `params_total`,
  `params_active` (= total for dense; < total for MoE, e.g. Qwen3-30B-A3B →
  30B/3B), `num_layers`, `hidden_size`, `context_length`, `modality`
  (`text|vision|audio|multimodal`), `license`, `openness` tier
  (`open-permissive|open-restricted|gated|closed`), `hf_downloads`, `hf_likes`,
  `last_modified`, and `quants: list[QuantVariant]`.
- **`QuantVariant`** (frozen): `format` (e.g. `GGUF Q4_K_M`, `Q8_0`, `AWQ`,
  `GPTQ-Int4`, `MLX-4bit`, `MLX-8bit`, `FP16`, `BF16`), `bits_per_weight`
  (effective float), `file_size_gb` (from source when available; else None),
  `est_memory_gb_4k`, `est_memory_gb_32k` (computed — §2), `source`
  (`hf:<repo>` | `ollama:<tag>` | `manual`), `platform` (`generic|apple_mlx`),
  `perf_tokens_per_sec` (optional), `perf_device` (optional; e.g. "M3 Max").

Every field optional where a source may not supply it; absent data renders as
"unknown", never blocks.

## 2. Deterministic memory estimator

`src/radar/models_radar/memory.py`:

```
estimate_memory_gb(params_total, bits_per_weight, context,
                   num_layers, hidden_size) -> float
  weights_gb  = params_total * bits_per_weight / 8 / 1e9
  # KV cache (fp16, 2 bytes; factor 2 for K and V). Non-GQA upper bound —
  # GQA models use less; we prefer to over- not under-estimate memory.
  kv_cache_gb = 2 * 2 * num_layers * context * hidden_size / 1e9
  return round((weights_gb + kv_cache_gb) * OVERHEAD, 1)   # OVERHEAD ≈ 1.2
```

When `num_layers`/`hidden_size` are unknown for a model, the KV term is omitted
and the estimate is weights-only (flagged approximate). The estimator is a pure
function — easy to refine (e.g. GQA-aware) in a later pass without touching callers.

- Computed, not scraped — consistent across all models and the exact substrate
  the hardware-matching phase compares to device memory.
- Evaluated at two reference contexts (4K, 32K) so each quant shows a range.
- MoE: **total** params drive memory (all experts resident); **active** params
  are recorded for the speed/capability signal, not the memory term.
- `file_size_gb` from HF/Ollama, when present, validates the weights term (a
  large divergence is surfaced as a warning, not silently trusted).

## 3. Recommendation + hardware tier

`src/radar/models_radar/scoring.py` — deterministic, model-specific:

- **Adoption ring** (reuse `Ring` adopt/pilot/watch) from a score over:
  **openness** (open weights + permissive license), **local-runnability**
  (smallest viable quant's `est_memory_gb`), **capability tier** (param/MoE size
  class), **ecosystem support** (GGUF/MLX/AWQ availability + Ollama presence),
  **momentum** (downloads/likes growth). Tag-free, fully deterministic.
- **Minimum viable quant** (used by both local-runnability and the tier badge):
  the quant with the lowest `est_memory_gb_4k` at or above a quality floor
  (≥ ~4 effective bits — i.e. Q4-class or better; sub-4-bit quants like Q2/Q3 are
  recorded but not treated as the "viable" minimum). The floor is a module constant.
- **Hardware-tier badge** from the *minimum viable quant's* memory:
  `laptop ≤16GB` · `apple/high-RAM ≤32GB` · `single-GPU ≤48GB` ·
  `workstation/multi-GPU ≤180GB` · `datacenter >180GB`. Thresholds are module
  constants. This badge is the bridge to sub-project 3.

## 4. Sources & collectors

`src/radar/models_radar/collectors/`, each best-effort (mirror the `_safe`
degrade-to-warning pattern; failures never abort the scan):

- **`huggingface.py`** — HF Hub API (`/api/models/{id}`): safetensors param
  counts, downloads, likes, license, `pipeline_tag` (modality), last-modified,
  sibling files to detect GGUF/AWQ/GPTQ/**MLX** quant repos. No key for public.
- **`ollama.py`** — Ollama library tags → local-runnable quant variants + sizes.
- **`manual.py`** — hand-entered specs for flagships, closed-but-notable models,
  and MLX tokens/sec numbers the APIs don't expose.
- **`config/model-seed.yaml`** — tracked model families (mirrors
  `seed-sources.yaml`): `id`, `family`, `hf_repo`, `ollama_name`, `backer`, and
  optional manual spec overrides. Seeded with current SOTA local models
  (Llama, Qwen3 + MoE, DeepSeek, Mistral, gpt-oss, Gemma, Phi…).
- Quant variants for a model are the union of HF sibling-derived, Ollama-tag, and
  manual entries, de-duplicated by `(format, platform)`.

## 5. Storage / history / momentum (reuse)

- **`model_metrics`** SQLite table (mirrors `project_metrics`): one row per model
  per scan — `downloads`, `likes`, `min_est_memory_gb`, `ring`, `hardware_tier`.
  Time-series; additive-migration pattern from the metrics store.
- **Model history log** `data/model-history.jsonl` (mirrors `history.jsonl`) for
  ring changes / new models; CI commits it like the tool history.
- Reuse **momentum** for "rising models" (download growth).
- Reuse the **discovery→proposals** flow: HF-trending models not in the seed →
  `data/proposed-model-seeds.yaml` for human review (never auto-added).

## 6. Surface

- **Dashboard "Models" section** (live `app.py` route + static export), reusing
  the existing templating/badge patterns. Per-model card: name + backer + ring +
  hardware-tier badge, params (total/active), context, license/openness, modality,
  and a **quant table** (format · bits · file size · est memory @4K/@32K ·
  platform · tok/s) with MLX rows flagged. Client-side sort/filter by hardware
  tier and `max_memory_gb` (the "what can I run" precursor).
- **MCP tools** (`mcp_server/`): `list_models` (filter by
  family/modality/`max_memory_gb`/hardware_tier), `get_model` (full spec + quant
  table), and a model movers/compare analog. The future hardware-match query
  slots in here.
- **Reports/feeds**: model movers + new-model events in the existing
  report/Atom/JSON outputs.

## 7. Pipeline & orchestration

- A **model pipeline** mirroring the tool scan: collect (HF + Ollama + manual) →
  assemble `ModelEntry` + compute quant memory → score → ring → diff vs previous
  scan → persist (`model_metrics` + `model-history.jsonl`) → render
  `model_cards.json` into the shared run dir.
- Integrated into the daily scan as its own stage, **plus** a `radar models`
  CLI subcommand group (`list`, `scan`, `export`) for standalone use. CI
  `publish.yml` picks it up via the same scan invocation.

## Error handling

Every network call is best-effort and wrapped like the existing collectors/
enrichers: a failure appends to a warnings list (surfaced via the existing
scan-health plumbing) and never aborts the run. A model the seed names but no
source can resolve renders with whatever specs exist (or manual overrides),
flagged incomplete rather than dropped.

## Testing

Mirror the existing collector/pipeline test style (`FakeClient` returning canned
HF/Ollama JSON; no live network in unit tests):

- **Estimator**: known-model spot checks (e.g. an 8B Q4 ≈ expected GB; a 30B-A3B
  MoE memory uses 30B not 3B; KV cache grows with context); pure-function, exact.
- **Collectors**: HF/Ollama parse fixtures → `ModelEntry`/`QuantVariant`; MLX quant
  detection; graceful degradation on network failure.
- **Scoring/ring + hardware tier**: deterministic threshold tests at each tier
  boundary; openness/runnability/momentum inputs → expected ring.
- **Storage**: `model_metrics` round-trip + additive migration; history-log diff.
- **Surface**: static-site renders the Models section + quant table; MCP
  `list_models` filters by `max_memory_gb`/hardware_tier; back-compat when no
  models exist.
- Keep ruff + mypy clean and coverage ≥ 80%.

## Verification

- Unit suites above green; `ruff check src tests`, `mypy src`, `pytest -q` clean.
- Live smoke (no key): resolve one HF model (e.g. a Qwen3 repo) → confirm params,
  downloads, and at least one quant variant with a sane `est_memory_gb`; resolve
  one Ollama model → confirm quant tags + sizes.
- `radar models scan --root .` then `radar models list` → models with rings +
  hardware tiers; `radar export` → Models section renders; MCP `list_models
  max_memory_gb=24` returns only models whose smallest viable quant fits.

## Out of scope (sub-project 3, separate cycle)

Matching the catalog against a user's actual device(s) — entering/detecting GPU/
RAM/Apple-Silicon specs and answering "can this machine run model X at quant Q
and context C?" This design deliberately produces the per-quant memory footprints
and hardware-tier badges that that phase will consume.
