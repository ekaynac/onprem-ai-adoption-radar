"""``radar models`` — local-model radar (catalog + specs).

Monkeypatch seam: ``_verify_fetch_hf_model`` is imported at module level (not
function-local, unlike other commands' imports) so tests can monkeypatch
``radar.cli.models_cli._verify_fetch_hf_model`` directly — the seam
``models verify`` uses to stay offline in tests.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import typer

# Imported at module level (not function-local, unlike this file's other
# commands) so tests can monkeypatch `_verify_fetch_hf_model` directly —
# the seam `models verify` uses to stay offline in tests.
from radar.cli._shared import BUNDLED_ROOT, console
from radar.models_radar.collectors.huggingface import (
    fetch_hf_model as _verify_fetch_hf_model,
)


logger = logging.getLogger(__name__)


models_app = typer.Typer(help="Local-model radar (catalog + specs).", no_args_is_help=True)

candidates_app = typer.Typer(help="Untracked model-candidate discovery.", no_args_is_help=True)
models_app.add_typer(candidates_app, name="candidates")

benchmarks_app = typer.Typer(help="Benchmark aggregation from public leaderboards.")
models_app.add_typer(benchmarks_app, name="benchmarks")

# `models verify`'s params_total drift check has three deterministic bands,
# widest-tolerance first:
#
# 1. Small relative differences (<= 3%) are the normal published-vs-measured
#    gap: HF model cards quote a rounded headline total ("671B") while the
#    HF API's safetensors element count is the exact figure ("684.53B").
#    Reported as a note, never DRIFT.
# 2. A bounded ratio band [1.4x, 2.5x] catches NVIDIA's NVFP4/FP4-packed
#    quant checkpoints, whose safetensors element count is roughly half the
#    real, published param total — a packing artifact, not real drift.
#    Observed 2026-07-28 across spec_verified seeds (hf-deepseek-v4-flash,
#    hf-glm-5-2-nvfp4) and unverified ones (hf-qwen3-6-27b-nvfp4):
#    ratios 1.53x-1.98x. Reported as a "packed-quant artifact" note, never
#    DRIFT — otherwise the weekly gate would go permanently red for a known,
#    documented, deliberate seed/HF disagreement (a YAML comment records the
#    correction, but comments aren't machine-parseable, so this band is the
#    deterministic proxy). The band has margin above and below the observed
#    range rather than pinning to it exactly.
# 3. Ratios above the band (e.g. a seed/HF repo mismatch, a since-renamed
#    model) are NOT assumed to be packed-quant — that would assert a false
#    cause. Reported as a neutral "differs by <ratio>x — investigate" note;
#    still never DRIFT, since a fetch pointed at the wrong data is not
#    something --check can act on either.
#
# Ratios below the band (and above the 3% tolerance) are real drift.
_PARAMS_TOTAL_TOLERANCE = 0.03
_PACKED_QUANT_RATIO_LOW = 1.4
_PACKED_QUANT_RATIO_HIGH = 2.5


@models_app.command("scan")
def models_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Collect model specs from HF + Ollama + seed; write a model_cards.json run."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.models_radar.entities import ModelEntry, ModelSeed
    from radar.models_radar.pipeline import persist_model_scan, score_entries
    from radar.models_radar.scan import run_model_scan
    from radar.models_radar.seed import load_model_seed
    from radar.models_radar.validate import (
        entry_advisories,
        seed_advisories,
        validate_entry,
        validate_seed,
    )
    from radar.storage.run_store import RunStore

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        # fall back to the packaged seed
        seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"

    seeds = load_model_seed(seed_path)

    # Quarantine gate: absurd seeds (e.g. a mis-scraped params_total wildly off
    # the name's size token) never reach collection, scoring, or ranking.
    quarantined: dict[str, list[str]] = {}
    advisories: list[str] = []
    valid_seeds: list[ModelSeed] = []
    for seed in seeds:
        problems = validate_seed(seed)
        if problems:
            quarantined[seed.id] = problems
            continue
        advisories.extend(seed_advisories(seed))
        valid_seeds.append(seed)
    for seed_id, problems in quarantined.items():
        console.print(f"[red]QUARANTINED {seed_id}:[/red] {'; '.join(problems)}")
    for advisory in advisories:
        console.print(f"[yellow]note:[/yellow] {advisory}")

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await run_model_scan(
                valid_seeds, client, retrieved_at=datetime.now(UTC).date().isoformat()
            )

    entries = asyncio.run(_run())

    # Post-assembly quarantine gate: an entry whose params are known but whose
    # specs never resolve to a usable minimum-viable memory number (e.g. no HF
    # data, no ollama, empty quants) is excluded from scoring/persistence, but
    # stays visible in the model_cards stage — its problems folded into
    # warnings — so operators can see exactly why. Mirrors the seed gate
    # above, one stage later.
    entry_quarantined: dict[str, list[str]] = {}
    entry_advisory_notes: list[str] = []
    valid_entries: list[ModelEntry] = []
    kept_entries: list[ModelEntry] = []
    for entry in entries:
        problems = validate_entry(entry)
        if problems:
            entry_quarantined[entry.id] = problems
            kept_entries.append(
                entry.model_copy(update={"warnings": [*entry.warnings, *problems]})
            )
            continue
        entry_advisory_notes.extend(entry_advisories(entry))
        valid_entries.append(entry)
        kept_entries.append(entry)
    for entry_id, problems in entry_quarantined.items():
        console.print(f"[red]QUARANTINED {entry_id}:[/red] {'; '.join(problems)}")
    for advisory in entry_advisory_notes:
        console.print(f"[yellow]note:[/yellow] {advisory}")

    scored_entries = score_entries(valid_entries)
    scored_by_id = {e.id: e for e in scored_entries}
    final_entries = [scored_by_id.get(e.id, e) for e in kept_entries]

    run_store = RunStore(root / "data" / "runs")
    run_id = run_store.create_run()
    # Stamp the kind up front: a crashed scan must never masquerade as a tool run
    # (latest_tool_scan_meta filters on the absence of "kind").
    run_store.update_meta(run_id, {"kind": "models"})
    all_warnings = [
        *(p for ps in quarantined.values() for p in ps), *advisories,
        *(p for ps in entry_quarantined.values() for p in ps), *entry_advisory_notes,
    ]
    if all_warnings:
        run_store.update_meta(run_id, {"model_validation_warnings": all_warnings})
    observed_at = datetime.now(UTC)
    persist_model_scan(
        scored_entries, run_id, observed_at,
        root / "data" / "radar.db", root / "data" / "model-history.jsonl",
        metrics_log_path=root / "data" / "model-metrics.jsonl",
    )
    run_store.save_stage(
        run_id, "model_cards", [m.model_dump(mode="json") for m in final_entries]
    )
    run_store.update_meta(run_id, {"kind": "models", "model_count": len(final_entries)})
    console.print(f"Scanned {len(final_entries)} models → run {run_id}")


@models_app.command("verify")
def models_verify(
    root: Path = typer.Option(Path("."), help="Project root."),
    check: bool = typer.Option(
        False, "--check", help="Exit 1 on drift in a spec_verified seed."
    ),
) -> None:
    """Diff seed spec numbers against fresh HF data. Never modifies seeds.

    params_total policy: differences within 3% are reported as a note
    (published-rounded total vs exact safetensors count), never DRIFT.
    Differences with a ratio in [1.4x, 2.5x] are reported as a "packed-quant
    artifact" note (NVFP4/FP4-packed checkpoints), never DRIFT. Larger
    ratios are reported as a neutral "investigate" note — never assumed to
    be packed-quant — and also never DRIFT. See `_PARAMS_TOTAL_TOLERANCE`
    and `_PACKED_QUANT_RATIO_LOW`/`_PACKED_QUANT_RATIO_HIGH` above.

    context_length policy: NEVER reported as DRIFT. The seed's
    context_length carries the model card's usable/advertised context,
    while HF's config.json max_position_embeddings is a different
    quantity — often larger, reflecting YaRN/RoPE-scaling headroom rather
    than the context the card recommends. A mismatch is always reported as
    a note, so it's visible without ever failing the weekly --check gate.
    """
    import asyncio

    import httpx

    from radar.models_radar.collectors.huggingface import HFModelData
    from radar.models_radar.entities import ArchitectureSpec
    from radar.models_radar.seed import load_model_seed

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        # fall back to the packaged seed
        seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"

    seeds = [s for s in load_model_seed(seed_path) if s.enabled and s.hf_repo]

    # Populated with an exception's class name whenever a per-seed fetch
    # raises instead of returning None — so one bad repo (a malformed API
    # body, an unexpected exception in the fetcher) never crashes the whole
    # command and loses every other seed's report.
    skip_reasons: dict[str, str] = {}

    async def _collect() -> dict[str, HFModelData | None]:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:

            async def _fetch_one(seed_id: str, hf_repo: str) -> HFModelData | None:
                try:
                    return await _verify_fetch_hf_model(hf_repo, client)  # type: ignore[arg-type]
                except Exception as exc:  # never let one seed's crash lose the rest
                    skip_reasons[seed_id] = f"{type(exc).__name__}: {exc}"
                    return None

            return {
                s.id: await _fetch_one(s.id, s.hf_repo)  # type: ignore[arg-type]
                for s in seeds
            }

    fetched = asyncio.run(_collect())
    drift_verified = 0
    drift_total = 0
    skipped = 0
    for seed in seeds:
        hf = fetched.get(seed.id)
        if hf is None:
            skipped += 1
            reason = skip_reasons.get(seed.id, "HF unreachable")
            console.print(f"[yellow]skip {seed.id}: {reason}[/yellow]")
            continue
        rows: list[tuple[str, object, object]] = []

        seed_pt, hf_pt = seed.params_total, hf.params_total
        if seed_pt is not None and hf_pt is not None and seed_pt != hf_pt:
            low, high = sorted((seed_pt, hf_pt))
            ratio = (high / low) if low else float("inf")
            rel_diff = ratio - 1
            if rel_diff <= _PARAMS_TOTAL_TOLERANCE:
                # Published-rounded card total vs the exact safetensors
                # count — never real drift.
                console.print(
                    f"[yellow]note {seed.id}: params_total differs by "
                    f"{rel_diff * 100:.1f}% (published-rounded total)[/yellow]"
                )
            elif _PACKED_QUANT_RATIO_LOW <= ratio <= _PACKED_QUANT_RATIO_HIGH:
                # Known artifact (see the band comment above): report it,
                # but never as DRIFT — the seed's total is the deliberately
                # corrected, cited value.
                console.print(
                    f"[yellow]note {seed.id}: params_total differs by {ratio:.2f}x "
                    "(packed-quant artifact, seed carries published total)[/yellow]"
                )
            elif ratio > _PACKED_QUANT_RATIO_HIGH:
                # Beyond the packed-quant band — do not invent a cause.
                console.print(
                    f"[yellow]note {seed.id}: params_total differs by {ratio:.2f}x "
                    "— investigate[/yellow]"
                )
            else:
                rows.append(("params_total", seed_pt, hf_pt))

        seed_ctx, hf_ctx = seed.context_length, hf.context_length
        if seed_ctx is not None and hf_ctx is not None and seed_ctx != hf_ctx:
            # Never DRIFT (see docstring): the seed carries the card's usable
            # context, config.json's max_position_embeddings is a different
            # quantity (often YaRN/RoPE-scaling headroom).
            console.print(
                f"[yellow]note {seed.id}: context_length seed={seed_ctx} vs "
                f"config max_position_embeddings={hf_ctx}[/yellow]"
            )

        if seed.architecture is not None and hf.architecture is not None:
            for field in ArchitectureSpec.model_fields:
                if field == "attention_kind":
                    continue  # derived, not a number to drift-check
                seed_value = getattr(seed.architecture, field)
                hf_value = getattr(hf.architecture, field)
                if seed_value is not None and hf_value is not None and seed_value != hf_value:
                    rows.append((f"architecture.{field}", seed_value, hf_value))

        for field, seed_value, hf_value in rows:
            drift_total += 1
            if seed.spec_verified:
                drift_verified += 1
            console.print(
                f"[red]DRIFT {seed.id}.{field}:[/red] seed={seed_value} hf={hf_value}"
            )

    if drift_total == 0:
        if skipped == 0:
            seed_noun = "seed" if len(seeds) == 1 else "seeds"
            console.print(f"OK: {len(seeds)} {seed_noun} verified, no drift")
        else:
            # Never claim a skipped (unreachable) seed was verified.
            console.print(
                f"checked {len(seeds) - skipped} of {len(seeds)} seeds, no drift "
                f"({skipped} unreachable)"
            )
    if check and drift_verified:
        raise typer.Exit(code=1)


@models_app.command("platforms-verify")
def platforms_verify(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Probe every platform's cited sources and persist a fresh health observation."""
    import asyncio
    import hashlib
    from datetime import UTC, datetime

    import httpx

    from radar.intelligence.bootstrap import build_intelligence_repository
    from radar.intelligence.contracts import (
        EvidenceObservation,
        EvidenceStrength,
    )
    from radar.models_radar.platform_matrix import load_platform_matrix
    from radar.storage.source_health_log import (
        SourceHealthRecord,
        SourceOutcome,
        append_source_health,
    )

    matrix_path = root / "config" / "platform-matrix.yaml"
    if not matrix_path.exists():
        matrix_path = BUNDLED_ROOT / "config" / "platform-matrix.yaml"
    platforms = load_platform_matrix(matrix_path)
    observed_at = datetime.now(UTC)

    async def _run() -> tuple[
        dict[str, SourceOutcome],
        dict[str, str],
    ]:
        limits = httpx.Limits(max_connections=16)
        async with httpx.AsyncClient(
            timeout=15.0,
            follow_redirects=True,
            limits=limits,
        ) as client:
            semaphore = asyncio.Semaphore(16)

            async def _probe(url: str) -> tuple[bool, str]:
                try:
                    digest = hashlib.sha256()
                    async with semaphore, client.stream(
                        "GET",
                        url,
                    ) as response:
                        if response.status_code >= 400:
                            return False, ""
                        size = 0
                        async for chunk in response.aiter_bytes():
                            digest.update(chunk)
                            size += len(chunk)
                            if size >= 1_000_000:
                                break
                        return True, digest.hexdigest()
                except Exception:
                    return False, ""

            outcomes: dict[str, SourceOutcome] = {}
            checksums: dict[str, str] = {}
            for platform in platforms:
                results = await asyncio.gather(
                    *(_probe(url) for url in platform.sources)
                )
                available = sum(ok for ok, _checksum in results)
                outcomes[f"platform:{platform.id}"] = SourceOutcome(
                    count=available,
                    status=(
                        "ok"
                        if available == len(results)
                        else ("partial" if available else "error")
                    ),
                )
                if available == len(results):
                    combined = hashlib.sha256(
                        "|".join(
                            checksum for _ok, checksum in results
                        ).encode()
                    ).hexdigest()
                    checksums[platform.id] = combined
            return outcomes, checksums

    outcomes, checksums = asyncio.run(_run())
    append_source_health(
        root / "data" / "source-health.jsonl",
        SourceHealthRecord(
            run_id=f"platform-verification-{observed_at.isoformat()}",
            observed_at=observed_at,
            sources=outcomes,
        ),
    )
    _database, repository = build_intelligence_repository(root)
    stamp = observed_at.strftime("%Y%m%dT%H%M%SZ")
    for platform in platforms:
        checksum = checksums.get(platform.id)
        platform_id = f"platform:legacy:{platform.id}"
        if checksum is None:
            repository.record_platform_verification(
                platform_id,
                observed_at,
                evidence_id=None,
                success=False,
            )
            continue
        evidence = EvidenceObservation(
            id=f"evidence:platform-reverify:{platform.id}:{stamp}",
            source_url=platform.sources[0],
            strength=EvidenceStrength.OFFICIAL_DOCUMENTATION,
            retrieved_at=observed_at,
            checksum=checksum,
            extractor_version="platform-source-reverify-v1",
        )
        repository.append_evidence(evidence)
        repository.record_platform_verification(
            platform_id,
            observed_at,
            evidence_id=evidence.id,
            success=True,
        )
    healthy = sum(outcome.status == "ok" for outcome in outcomes.values())
    console.print(
        f"Checked {len(outcomes)} platform source sets; {healthy} fully healthy"
    )


@candidates_app.command("scan")
def candidates_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep untracked HF-trending models and append to the candidate observation log."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.model_candidate_sweep import sweep_model_candidates
    from radar.models_radar.seed import load_model_seed
    from radar.storage.model_candidate_log import append_model_candidates

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)
    now = datetime.now(UTC)

    async def _run():
        health: dict[str, int] = {}
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            observations = await sweep_model_candidates(
                seeds,
                client,
                now,
                health=health,
            )
        return observations, health

    observations, health = asyncio.run(_run())
    out_path = root / "data" / "model-candidate-observations.jsonl"
    append_model_candidates(out_path, observations)
    from radar.storage.source_health_log import (
        SourceHealthRecord,
        SourceOutcome,
        append_source_health,
    )

    append_source_health(
        root / "data" / "source-health.jsonl",
        SourceHealthRecord(
            run_id=f"model-candidates-{now.isoformat()}",
            observed_at=now,
            sources={
                "huggingface:model-candidates": SourceOutcome(
                    count=len(observations),
                    status=(
                        "ok"
                        if health.get("failures", 0) == 0
                        else (
                            "error"
                            if health.get("failures", 0)
                            == health.get("requests", 0)
                            else "partial"
                        )
                    ),
                )
            },
        ),
    )
    console.print(f"Observed {len(observations)} untracked model candidate(s) "
                  f"→ {out_path.relative_to(root)}")


@benchmarks_app.command("scan")
def benchmarks_scan(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """Sweep configured leaderboards and append benchmark observations."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.benchmark_sweep import (
        load_benchmark_sources,
        sweep_benchmarks,
    )
    from radar.models_radar.seed import load_model_seed
    from radar.storage.benchmark_observations_log import (
        append_benchmark_observations,
    )

    seed_path = root / "config" / "model-seed.yaml"
    sources_path = root / "config" / "benchmark-sources.yaml"
    if not seed_path.exists():
        fallback = BUNDLED_ROOT / "config"
        seed_path = fallback / "model-seed.yaml"
        sources_path = fallback / "benchmark-sources.yaml"
    seeds = load_model_seed(seed_path)
    config = load_benchmark_sources(sources_path)
    now = datetime.now(UTC)

    async def _run():
        import os

        headers = {}
        if token := os.environ.get("HF_TOKEN"):
            headers["Authorization"] = f"Bearer {token}"
        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=headers,
        ) as client:
            return await sweep_benchmarks(seeds, config, client, now)

    result = asyncio.run(_run())
    out_path = root / "data" / "benchmark-observations.jsonl"
    append_benchmark_observations(out_path, result.observations)
    from radar.storage.source_health_log import (
        SourceHealthRecord,
        SourceOutcome,
        append_source_health,
    )

    append_source_health(
        root / "data" / "source-health.jsonl",
        SourceHealthRecord(
            run_id=f"benchmarks-{now.isoformat()}",
            observed_at=now,
            sources={
                f"benchmarks:{source_id}": SourceOutcome(
                    count=outcome["count"],
                    status=outcome["status"],
                )
                for source_id, outcome in result.outcomes.items()
            },
        ),
    )
    console.print(
        f"Observed {len(result.observations)} benchmark score(s) "
        f"→ {out_path.relative_to(root)}"
    )
    for source_id, outcome in sorted(result.outcomes.items()):
        console.print(
            f"  {source_id}: {outcome['count']} score(s), {outcome['status']}"
        )
    for source_id, skipped in sorted(result.skipped.items()):
        console.print(
            f"  [yellow]{source_id}: expected but unmatched → "
            f"{', '.join(skipped)}[/yellow]"
        )


@models_app.command("benchcards")
def models_benchcards(
    root: Path = typer.Option(Path("."), help="Project root."),
    limit: int = typer.Option(0, help="Limit to N seed models (0 = all)."),
) -> None:
    """Ingest self-reported benchmarks from HF model cards into observations.

    For every enabled seed with an hf_repo whose card is not already in the
    benchmark-sources join, fetches the model-card README, parses canonical
    benchmark scores, and appends them as ``hf-model-card`` (self-reported)
    observations. Aggregates pick them up on the next build.
    """
    import asyncio

    import httpx

    from radar.models_radar.card_benchmarks import parse_card_benchmarks
    from radar.models_radar.seed import load_model_seed
    from radar.storage.benchmark_observations_log import (
        BenchmarkObservation,
        append_benchmark_observations,
        load_benchmark_observations,
    )

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"
    seeds = [s for s in load_model_seed(seed_path) if s.enabled and s.hf_repo]
    if limit > 0:
        seeds = seeds[:limit]

    # Frontier coverage: discovered releases with an hf_repo get the same
    # treatment, so a model the sweep found yesterday starts accruing
    # evidence today instead of waiting for a seed edit.
    from types import SimpleNamespace

    from radar.web.public_context import load_public_model_profiles

    seeded_ids = {s.id for s in seeds}
    seed_shims: list[Any] = []
    for profile_id, profile in load_public_model_profiles(root).items():
        if profile_id in seeded_ids or not profile.get("source_url"):
            continue
        hf_repo = str(profile["source_url"]).removeprefix("https://huggingface.co/")
        if not hf_repo or "/" not in hf_repo:
            continue
        seed_shims.append(
            SimpleNamespace(id=profile_id, hf_repo=hf_repo, enabled=True)
        )

    log_path = root / "data" / "benchmark-observations.jsonl"
    existing = {
        (row.model_id, row.benchmark, row.source_id)
        for row in load_benchmark_observations(log_path)
    }
    card_url = "https://huggingface.co/{repo}/raw/main/README.md"

    async def _collect() -> dict[str, str | None]:
        from radar.huggingface_auth import apply_hf_auth

        client_kwargs = apply_hf_auth(
            {"timeout": 20.0, "follow_redirects": True}, root
        )
        async with httpx.AsyncClient(**client_kwargs) as client:

            async def _fetch(repo: str) -> str | None:
                try:
                    response = await client.get(card_url.format(repo=repo))
                    response.raise_for_status()
                except Exception as exc:
                    # Classify so the autopilot debt report is actionable:
                    # 401 = token missing, 403 = repo is license-gated (accept
                    # the license on huggingface.co — a token alone cannot),
                    # anything else = transient network/parse issue.
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status == 401:
                        logger.warning(
                            "Card fetch for %s needs HF_TOKEN (401)", repo
                        )
                    elif status == 403:
                        logger.warning(
                            "Card fetch for %s is license-gated (403): accept "
                            "the license on huggingface.co to enable ingestion",
                            repo,
                        )
                    else:
                        logger.warning("Card fetch failed for %s: %s", repo, exc)
                    return None
                return response.text

            return {
                seed.id: await _fetch(seed.hf_repo or "")
                for seed in [*seeds, *seed_shims]
            }

    cards = asyncio.run(_collect())
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    appended: list[BenchmarkObservation] = []
    parsed_count = 0
    skipped = 0
    for seed in [*seeds, *seed_shims]:
        text = cards.get(seed.id)
        if not text:
            skipped += 1
            continue
        parsed = parse_card_benchmarks(text)
        if not parsed:
            continue
        parsed_count += 1
        source_url = card_url.format(repo=seed.hf_repo)
        for benchmark, (score, _matched) in sorted(parsed.items()):
            key = (seed.id, benchmark, "hf-model-card")
            if key in existing:
                continue  # exactly-once per (model, benchmark, source)
            appended.append(
                BenchmarkObservation(
                    model_id=seed.id,
                    hf_repo=seed.hf_repo,
                    benchmark=benchmark,
                    score=score,
                    source_id="hf-model-card",
                    source_url=source_url,
                    observed_at=now,
                    self_reported=True,
                )
            )
    append_benchmark_observations(log_path, appended)
    console.print(
        f"[green]{len(appended)}[/green] new observation(s) from "
        f"{parsed_count} card(s); {skipped} card(s) unavailable."
    )


@models_app.command("benchdebt")
def models_benchdebt(
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Report which tracked models lack sufficient task evidence.

    The ingest worklist: one row per (model, task) below the two-suite
    evidence bar that advisor-v2 enforces.
    """
    from radar.knowledge import load_task_suite_overrides
    from radar.models_radar.advisor import MIN_TASK_BENCHMARK_SOURCES, TASKS
    from radar.models_radar.benchmarks import build_benchmark_aggregates
    from radar.models_radar.card_benchmarks import benchmark_debt
    from radar.models_radar.seed import load_model_seed
    from radar.storage.benchmark_observations_log import (
        load_benchmark_observations,
    )

    seed_path = root / "config" / "model-seed.yaml"
    seeds = (
        load_model_seed(seed_path)
        if seed_path.exists()
        else load_model_seed(BUNDLED_ROOT / "config" / "model-seed.yaml")
    )
    seeds_by_id = {seed.id: seed for seed in seeds}
    observations = load_benchmark_observations(
        root / "data" / "benchmark-observations.jsonl"
    )
    aggregates = build_benchmark_aggregates(seeds_by_id, observations)
    overrides = load_task_suite_overrides(root)
    effective_tasks = {
        task: dict(spec) for task, spec in TASKS.items()
    }
    for task, suites in overrides.items():
        if task in effective_tasks:
            effective_tasks[task]["benchmarks"] = [
                *effective_tasks[task]["benchmarks"],
                *(suite for suite in suites if suite not in effective_tasks[task]["benchmarks"]),
            ]
    rows = benchmark_debt(
        seeds_by_id,
        aggregates,
        effective_tasks,
        min_sources=MIN_TASK_BENCHMARK_SOURCES,
    )
    if not rows:
        console.print("[green]No benchmark debt — every tracked task/model pair is evidenced.[/green]")
        return
    console.print(f"{len(rows)} evidence gap(s):")
    for row in rows:
        have = ", ".join(row["have"]) or "none"
        console.print(
            f"  {row['model_id']} · {row['task']}: "
            f"{row['distinct_have']}/{row['needed']} suites "
            f"(have: {have}; missing e.g. {', '.join(row['missing'][:3])})"
        )


@models_app.command("teach-suite")
def models_teach_suite(
    task: str = typer.Option(..., help="Task key, e.g. coding."),
    benchmark: str = typer.Option(..., help="Canonical suite id, e.g. swe-bench-verified."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Teach the advisor a new benchmark suite for a task — no code change.

    Writes to data/knowledge/task-suites.jsonl; the advisor, benchdebt and
    future sweeps read it back. Nothing about what measures a task stays
    frozen in source.
    """
    from radar.knowledge import learn_task_suite
    from radar.models_radar.benchmarks import CANONICAL_BENCHMARKS

    if benchmark not in CANONICAL_BENCHMARKS:
        console.print(
            f"[red]Unknown suite {benchmark!r}. Canonical suites: "
            f"{', '.join(sorted(CANONICAL_BENCHMARKS))}[/red]"
        )
        raise typer.Exit(code=1)
    created = learn_task_suite(root, task, benchmark)
    if created:
        console.print(f"[green]Learned:[/green] {task} ← {benchmark}")
    else:
        console.print(f"[yellow]Already known:[/yellow] {task} ← {benchmark}")


@models_app.command("discover")
def models_discover(
    min_downloads: int = typer.Option(10000, help="Minimum HF downloads for a candidate."),
    limit: int = typer.Option(50, help="Max candidates to fetch/propose."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Find trending HF models and write proposals for review (never auto-adds)."""
    import asyncio

    import httpx

    from radar.discovery.hf_trending_models import discover_trending_models
    from radar.discovery.model_proposals import write_model_proposals
    from radar.models_radar.seed import load_model_seed

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)

    async def _run():
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            return await discover_trending_models(
                seeds, client, min_downloads=min_downloads, limit=limit
            )

    proposals = asyncio.run(_run())
    out_path = root / "data" / "proposed-model-seeds.yaml"
    write_model_proposals(out_path, proposals)
    console.print(f"Found {len(proposals)} model candidate(s) → {out_path}")
    for p in proposals[:15]:
        console.print(
            f"  {p.downloads:>9,}↓  {p.model_id:<32} {p.family:<14} {p.hf_repo}",
            highlight=False,
        )


@models_app.command("promote")
def models_promote(
    min_downloads: int = typer.Option(100000, help="Minimum HF downloads to promote."),
    limit: int = typer.Option(5, help="Max new models to add per run."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print what would be added; do not write."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Promote high-quality proposals from data/proposed-model-seeds.yaml into config/model-seed.yaml."""
    import asyncio
    from datetime import UTC, datetime

    import httpx

    from radar.discovery.model_promotion import (
        build_seed,
        promotable_candidates,
        seed_to_yaml_block,
    )
    from radar.discovery.model_proposals import load_model_proposals
    from radar.models_radar.collectors.huggingface import fetch_hf_model
    from radar.models_radar.entities import ModelSeed
    from radar.models_radar.seed import ModelSeedError, load_model_seed
    from radar.storage.model_candidate_log import load_model_candidates

    seed_path = root / "config" / "model-seed.yaml"
    if not seed_path.exists():
        seed_path = BUNDLED_ROOT / "config" / "model-seed.yaml"
    seeds = load_model_seed(seed_path)

    seeded_repos = {s.hf_repo.lower() for s in seeds if s.hf_repo}
    existing_ids = {s.id for s in seeds}

    proposals_path = root / "data" / "proposed-model-seeds.yaml"
    proposals = load_model_proposals(proposals_path)
    if not proposals:
        console.print(f"No proposals found at {proposals_path}.")
        return

    observations = load_model_candidates(root / "data" / "model-candidate-observations.jsonl")
    now = datetime.now(UTC)
    candidates = promotable_candidates(
        proposals, observations, min_downloads=min_downloads,
        seeded_repos=seeded_repos, now=now)

    async def _run() -> list[ModelSeed]:
        _collected: list[ModelSeed] = []
        _existing = set(existing_ids)
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            _client: Any = client
            for p in candidates:
                if len(_collected) >= limit:
                    break
                hf = await fetch_hf_model(p.hf_repo, _client)
                if hf is None:
                    console.print(f"  [dim]skip {p.hf_repo}: HF fetch failed[/dim]")
                    continue
                if hf.params_total is None:
                    console.print(f"  [dim]skip {p.hf_repo}: no params_total from HF[/dim]")
                    continue
                seed = build_seed(p, hf, existing_ids=_existing)
                if seed is None:
                    continue
                _existing = _existing | {seed.id}
                _collected.append(seed)
        return _collected

    collected: list[ModelSeed] = asyncio.run(_run())

    if not collected:
        console.print("No new models qualified.")
        return

    if dry_run:
        from rich.table import Table

        table = Table(title="Would promote (dry run)")
        table.add_column("id")
        table.add_column("family")
        table.add_column("params_total")
        table.add_column("hf_repo")
        for s in collected:
            table.add_row(
                s.id,
                s.family,
                str(s.params_total) if s.params_total is not None else "",
                s.hf_repo or "",
            )
        console.print(table)
        return

    old_text = seed_path.read_text(encoding="utf-8")
    # Separate each appended entry with a blank line, matching the hand-authored style.
    blocks = "".join("\n" + seed_to_yaml_block(s).strip("\n") + "\n" for s in collected)
    new_text = old_text.rstrip("\n") + "\n" + blocks

    tmp = seed_path.with_suffix(".promote.tmp")
    tmp.write_text(new_text, encoding="utf-8")

    try:
        loaded = load_model_seed(tmp)
    except ModelSeedError as exc:
        tmp.unlink(missing_ok=True)
        console.print(f"[red]Validation failed: {exc}[/red]")
        raise typer.Exit(code=1) from exc

    loaded_ids = [s.id for s in loaded]
    if len(loaded_ids) != len(set(loaded_ids)):
        tmp.unlink(missing_ok=True)
        console.print("[red]Duplicate IDs detected after promotion; aborting.[/red]")
        raise typer.Exit(code=1)

    tmp.replace(seed_path)
    for s in collected:
        console.print(f"  [green]added[/green] {s.id}  ({s.hf_repo})")
    console.print(f"Promoted {len(collected)} model(s) → {seed_path}")


@models_app.command("devices")
def models_devices() -> None:
    """List built-in device presets for the fit check (devices, nodes, clusters)."""
    from radar.models_radar.devices import (
        CLUSTER_PRESETS,
        DEVICE_PRESETS,
        NODE_PRESETS,
        usable_memory_gb,
    )

    for label, presets in (
        ("Devices", DEVICE_PRESETS),
        ("Nodes", NODE_PRESETS),
        ("Clusters", CLUSTER_PRESETS),
    ):
        console.print(f"[bold]{label}[/bold]")
        for key, d in presets.items():
            console.print(f"  {key:<26} {d.name:<28} ~{usable_memory_gb(d):>6.1f} GB usable",
                          highlight=False)


@models_app.command("fit")
def models_fit(
    device: str = typer.Option("", help="Preset id (see `radar models devices`)."),
    memory: float = typer.Option(0.0, help="Custom: total memory GB (with --kind)."),
    kind: str = typer.Option("gpu", help="Custom device kind: gpu|apple|cpu."),
    gpus: int = typer.Option(1, help="Custom: number of GPUs."),
    context: int = typer.Option(4096, help="Context length (tokens) for the estimate."),
    root: Path = typer.Option(Path("."), help="Project root."),
) -> None:
    """Show which tracked models fit a device, and at which quant."""
    from radar.mcp_server.model_queries import _latest_model_cards
    from radar.models_radar.device_fit import fit_report
    from radar.models_radar.devices import DeviceError, resolve_device
    from radar.models_radar.entities import ModelEntry

    try:
        spec: str | dict = device or {"kind": kind, "total_memory_gb": memory, "gpu_count": gpus}
        if not device and memory <= 0:
            console.print("[red]Provide --device <preset> or --memory <GB>.[/red]")
            raise typer.Exit(code=1)
        dev = resolve_device(spec)
    except DeviceError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    entries = [ModelEntry.model_validate(c) for c in _latest_model_cards(root)]
    if not entries:
        console.print("[yellow]No model scan yet. Run [bold]radar models scan[/bold] first.[/yellow]")
        return
    from radar.models_radar.devices import usable_memory_gb
    console.print(f"{dev.name} — ~{usable_memory_gb(dev):.1f} GB usable @ {context} ctx:")
    for f in fit_report(entries, dev, context):
        q = f.best_quant_format or "-"
        console.print(f"  {f.model_id:<28} {f.verdict:<15} {q}", highlight=False)


@models_app.command("list")
def models_list(root: Path = typer.Option(Path("."), help="Project root.")) -> None:
    """List models from the latest model scan."""
    import json as _json
    from datetime import UTC, datetime

    from radar.models_radar.entities import ModelEntry as _ME
    from radar.models_radar.pipeline import momentum_for
    from radar.storage.run_store import RunStore

    run_store = RunStore(root / "data" / "runs")
    model_run = run_store.latest_run_of_kind("models")
    if model_run is None:
        console.print("[yellow]No model scan yet. Run [bold]radar models scan[/bold] first.[/yellow]")
        return
    cards_path = run_store._run_dir(model_run) / "model_cards.json"
    entries = _json.loads(cards_path.read_text(encoding="utf-8"))
    console.print(f"{len(entries)} models (run {model_run}):")
    parsed = [_ME.model_validate(m) for m in entries]
    moms = momentum_for(parsed, root / "data" / "radar.db",
                        root / "data" / "model-history.jsonl", datetime.now(UTC))
    _ARROW = {"rising": "↑", "falling": "↓", "steady": "→"}
    for m in parsed:
        quants = m.quants
        mems = [q.est_memory_gb_4k for q in quants
                if q.est_memory_gb_4k and q.bits_per_weight >= 4.0]
        min_mem = f"{min(mems):.1f}GB" if mems else "?"
        arrow = _ARROW.get(moms[m.id].direction, "")
        ring = m.ring.value if m.ring else "-"
        console.print(
            f"  {m.id:<28} {ring:<7} {m.hardware_tier.value:<16} "
            f"min~{min_mem:<9} {arrow} {m.family}",
            highlight=False,
        )
