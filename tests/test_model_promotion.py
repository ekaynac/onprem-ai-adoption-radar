"""Tests for radar.discovery.model_promotion."""

from __future__ import annotations

from pathlib import Path

from radar.discovery.model_promotion import (
    backer_for_org,
    build_seed,
    derive_family,
    is_promotable,
    seed_to_yaml_block,
)
from radar.discovery.model_proposals import ModelProposal
from radar.models import BackerType
from radar.models_radar.collectors.huggingface import HFModelData
from radar.models_radar.entities import Modality, ModelSeed
from radar.models_radar.seed import load_model_seed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _proposal(
    *,
    hf_repo: str = "acme-org/Clean-Model-7B",
    name: str = "Clean Model 7B",
    family: str = "Clean Model",
    downloads: int = 100_000,
    modality: str = "text",
    suggested_id: str = "clean-model-7b",
) -> ModelProposal:
    return ModelProposal(
        model_id=suggested_id,
        name=name,
        family=family,
        hf_repo=hf_repo,
        downloads=downloads,
        likes=500,
        modality=modality,
        suggested_id=suggested_id,
    )


def _hf(
    *,
    params_total: int | None = 7_000_000_000,
    num_layers: int | None = 32,
    hidden_size: int | None = 4096,
    context_length: int | None = 8192,
    license: str | None = "apache-2.0",
    last_modified: str | None = "2025-03-15T10:00:00",
) -> HFModelData:
    return HFModelData(
        params_total=params_total,
        num_layers=num_layers,
        hidden_size=hidden_size,
        context_length=context_length,
        license=license,
        last_modified=last_modified,
    )


# ---------------------------------------------------------------------------
# is_promotable — rejections
# ---------------------------------------------------------------------------


class TestIsPromotableRejects:
    def test_rejects_gguf_repo(self) -> None:
        p = _proposal(hf_repo="acme/Clean-Model-7B-GGUF")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_awq_repo(self) -> None:
        p = _proposal(hf_repo="acme/Clean-Model-7B-AWQ")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_gptq_repo(self) -> None:
        p = _proposal(hf_repo="acme/Model-GPTQ")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_lora_repo(self) -> None:
        p = _proposal(hf_repo="acme/Model-7B-LoRA")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_thebloke_org(self) -> None:
        p = _proposal(hf_repo="TheBloke/Llama-7B-GGUF")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_bartowski_org(self) -> None:
        p = _proposal(hf_repo="bartowski/SomeModel-GGUF")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_unsloth_org(self) -> None:
        p = _proposal(hf_repo="unsloth/Llama-3-8B")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_below_floor_downloads(self) -> None:
        p = _proposal(downloads=500)
        assert not is_promotable(p, min_downloads=1_000, seeded_repos=set())

    def test_rejects_already_seeded_repo(self) -> None:
        p = _proposal(hf_repo="Qwen/Qwen3-8B")
        assert not is_promotable(
            p, min_downloads=1, seeded_repos={"qwen/qwen3-8b"}
        )

    def test_rejects_already_seeded_case_insensitive(self) -> None:
        p = _proposal(hf_repo="Meta-Llama/Llama-3-8B")
        assert not is_promotable(
            p, min_downloads=1, seeded_repos={"meta-llama/llama-3-8b"}
        )

    def test_rejects_non_text_modality_vision(self) -> None:
        p = _proposal(modality="vision")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_non_text_modality_audio(self) -> None:
        p = _proposal(modality="audio")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_rejects_unknown_modality(self) -> None:
        p = _proposal(modality="code")
        assert not is_promotable(p, min_downloads=1, seeded_repos=set())


# ---------------------------------------------------------------------------
# is_promotable — acceptance
# ---------------------------------------------------------------------------


class TestIsPromotableAccepts:
    def test_accepts_clean_high_download_text_model(self) -> None:
        p = _proposal()
        assert is_promotable(p, min_downloads=50_000, seeded_repos=set())

    def test_accepts_multimodal(self) -> None:
        p = _proposal(modality="multimodal")
        assert is_promotable(p, min_downloads=1, seeded_repos=set())

    def test_accepts_exactly_at_min_downloads(self) -> None:
        p = _proposal(downloads=50_000)
        assert is_promotable(p, min_downloads=50_000, seeded_repos=set())

    def test_accepts_different_case_org_not_republisher(self) -> None:
        p = _proposal(hf_repo="Qwen/Qwen3-72B")
        assert is_promotable(p, min_downloads=1, seeded_repos=set())


# ---------------------------------------------------------------------------
# backer_for_org
# ---------------------------------------------------------------------------


class TestBackerForOrg:
    def test_known_org_qwen(self) -> None:
        b = backer_for_org("qwen")
        assert b.name == "Alibaba"
        assert b.type == BackerType.BIG_TECH

    def test_known_org_case_insensitive(self) -> None:
        b = backer_for_org("Qwen")
        assert b.name == "Alibaba"

    def test_known_org_mistralai(self) -> None:
        b = backer_for_org("mistralai")
        assert b.name == "Mistral AI"
        assert b.type == BackerType.STARTUP

    def test_known_org_meta_llama(self) -> None:
        b = backer_for_org("meta-llama")
        assert b.name == "Meta"
        assert b.type == BackerType.BIG_TECH

    def test_known_org_deepseek(self) -> None:
        b = backer_for_org("deepseek-ai")
        assert b.name == "DeepSeek"
        assert b.type == BackerType.STARTUP

    def test_known_org_allenai(self) -> None:
        b = backer_for_org("allenai")
        assert b.type == BackerType.ACADEMIC

    def test_community_fallback(self) -> None:
        b = backer_for_org("some-unknown-org")
        assert b.name == "some-unknown-org"
        assert b.type == BackerType.COMMUNITY

    def test_community_fallback_preserves_case(self) -> None:
        b = backer_for_org("MyOrg")
        assert b.name == "MyOrg"


# ---------------------------------------------------------------------------
# derive_family
# ---------------------------------------------------------------------------


class TestDeriveFamily:
    def test_strips_size_b(self) -> None:
        assert derive_family("Qwen3-0.6B") == "Qwen3"

    def test_strips_size_and_instruct(self) -> None:
        assert derive_family("Llama-3.1-8B-Instruct") == "Llama-3.1"

    def test_strips_it_variant(self) -> None:
        assert derive_family("Gemma-3-12B-IT") == "Gemma-3"

    def test_strips_chat(self) -> None:
        assert derive_family("Mistral-7B-Chat") == "Mistral"

    def test_strips_base(self) -> None:
        assert derive_family("Phi-4-Base") == "Phi-4"

    def test_no_strip_when_nothing_to_strip(self) -> None:
        # Family token with no size/variant suffix
        assert derive_family("Qwen3") == "Qwen3"

    def test_name_with_only_strip_tokens_is_preserved(self) -> None:
        # Edge case: name that's entirely size tokens → return original
        result = derive_family("7B")
        assert result == "7B"

    def test_million_size_token(self) -> None:
        assert derive_family("SmolLM-360M") == "SmolLM"


# ---------------------------------------------------------------------------
# build_seed
# ---------------------------------------------------------------------------


class TestBuildSeed:
    def test_returns_none_when_hf_none(self) -> None:
        p = _proposal()
        assert build_seed(p, None, existing_ids=set()) is None

    def test_returns_none_when_params_total_none(self) -> None:
        p = _proposal()
        h = _hf(params_total=None)
        assert build_seed(p, h, existing_ids=set()) is None

    def test_fills_correct_fields(self) -> None:
        p = _proposal(
            hf_repo="meta-llama/Llama-3.1-8B-Instruct",
            name="Llama 3.1 8B Instruct",
            suggested_id="llama-3.1-8b-instruct",
        )
        h = _hf(
            params_total=8_000_000_000,
            num_layers=32,
            hidden_size=4096,
            context_length=131072,
            license="llama-3.1",
            last_modified="2024-07-23T12:00:00",
        )
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        assert seed.id == "llama-3.1-8b-instruct"
        assert seed.name == "Llama 3.1 8B Instruct"
        assert seed.params_total == 8_000_000_000
        assert seed.num_layers == 32
        assert seed.hidden_size == 4096
        assert seed.context_length == 131072
        assert seed.license == "llama-3.1"
        assert seed.release_date == "2024-07"
        assert seed.backer is not None
        assert seed.backer.name == "Meta"
        assert seed.backer.type == BackerType.BIG_TECH
        assert seed.ollama_name is None
        assert seed.params_active is None
        assert seed.use_case is None

    def test_modality_mapped_text(self) -> None:
        p = _proposal(modality="text")
        h = _hf()
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        assert seed.modality == Modality.TEXT

    def test_modality_mapped_multimodal(self) -> None:
        p = _proposal(modality="multimodal")
        h = _hf()
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        assert seed.modality == Modality.MULTIMODAL

    def test_makes_id_unique_against_existing(self) -> None:
        p = _proposal(suggested_id="clean-model-7b")
        h = _hf()
        seed = build_seed(p, h, existing_ids={"clean-model-7b", "clean-model-7b-2"})
        assert seed is not None
        assert seed.id == "clean-model-7b-3"

    def test_returns_none_when_all_ids_taken(self) -> None:
        p = _proposal(suggested_id="clash")
        h = _hf()
        taken = {"clash"} | {f"clash-{i}" for i in range(2, 52)}
        assert build_seed(p, h, existing_ids=taken) is None

    def test_release_date_none_when_no_last_modified(self) -> None:
        p = _proposal()
        h = _hf(last_modified=None)
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        assert seed.release_date is None

    def test_release_date_none_when_bad_format(self) -> None:
        p = _proposal()
        h = _hf(last_modified="not-a-date")
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        assert seed.release_date is None

    def test_openness_open_permissive(self) -> None:
        p = _proposal()
        h = _hf(license="apache-2.0")
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        from radar.models_radar.entities import Openness
        assert seed.openness == Openness.OPEN_PERMISSIVE

    def test_openness_open_restricted(self) -> None:
        p = _proposal()
        h = _hf(license="llama-3.1")
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        from radar.models_radar.entities import Openness
        assert seed.openness == Openness.OPEN_RESTRICTED

    def test_community_backer_fallback(self) -> None:
        p = _proposal(hf_repo="unknown-org/Model-7B")
        h = _hf()
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None
        assert seed.backer is not None
        assert seed.backer.name == "unknown-org"
        assert seed.backer.type == BackerType.COMMUNITY


# ---------------------------------------------------------------------------
# Round-trip: seed_to_yaml_block → load_model_seed
# ---------------------------------------------------------------------------


class TestRoundTrip:
    def test_round_trip_basic(self, tmp_path: Path) -> None:
        p = _proposal(
            hf_repo="meta-llama/Llama-3.1-8B-Instruct",
            name="Llama 3.1 8B Instruct",
            suggested_id="llama-3.1-8b-rt",
        )
        h = _hf(
            params_total=8_000_000_000,
            license="apache-2.0",
            last_modified="2024-07-01T00:00:00",
        )
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None

        block = seed_to_yaml_block(seed)
        yaml_content = f"models:\n{block}"
        seed_file = tmp_path / "model-seed.yaml"
        seed_file.write_text(yaml_content, encoding="utf-8")

        loaded = load_model_seed(seed_file)
        assert len(loaded) == 1
        loaded_seed = loaded[0]

        assert loaded_seed.id == seed.id
        assert loaded_seed.name == seed.name
        assert loaded_seed.family == seed.family
        assert loaded_seed.hf_repo == seed.hf_repo
        assert loaded_seed.params_total == seed.params_total
        assert loaded_seed.num_layers == seed.num_layers
        assert loaded_seed.hidden_size == seed.hidden_size
        assert loaded_seed.context_length == seed.context_length
        assert loaded_seed.license == seed.license
        assert loaded_seed.openness == seed.openness
        assert loaded_seed.release_date == seed.release_date
        assert loaded_seed.backer == seed.backer
        assert loaded_seed.modality == seed.modality

    def test_round_trip_minimal(self, tmp_path: Path) -> None:
        """Minimal seed (only required fields + params_total) round-trips."""
        seed = ModelSeed(
            id="test-model",
            name="Test Model 7B",
            family="Test Model",
            hf_repo="test-org/Test-Model-7B",
            params_total=7_000_000_000,
            backer=None,
            modality=None,
            license=None,
            openness=None,
            release_date=None,
        )
        block = seed_to_yaml_block(seed)
        yaml_content = f"models:\n{block}"
        seed_file = tmp_path / "model-seed.yaml"
        seed_file.write_text(yaml_content, encoding="utf-8")

        loaded = load_model_seed(seed_file)
        assert len(loaded) == 1
        assert loaded[0].id == "test-model"
        assert loaded[0].params_total == 7_000_000_000
        assert loaded[0].backer is None

    def test_seed_to_yaml_block_format(self) -> None:
        """Check that the YAML block starts with the list-item indicator."""
        p = _proposal()
        h = _hf()
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None

        block = seed_to_yaml_block(seed)
        # Use the raw block (not stripped) to verify indentation
        lines = block.splitlines()
        assert lines[0].startswith("  - id:")
        assert lines[1].startswith("    name:")

    def test_backer_inline_format(self) -> None:
        """Backer should render as inline YAML dict."""
        p = _proposal(hf_repo="meta-llama/Llama-3-8B", name="Llama 3 8B")
        h = _hf()
        seed = build_seed(p, h, existing_ids=set())
        assert seed is not None

        block = seed_to_yaml_block(seed)
        assert 'backer: {name: "Meta", type: big_tech}' in block

    def test_multiple_seeds_round_trip(self, tmp_path: Path) -> None:
        """Multiple blocks concatenated under 'models:' all load correctly."""
        seeds = [
            build_seed(
                _proposal(
                    hf_repo=f"acme-org/Model-{i}B",
                    name=f"Model {i}B",
                    suggested_id=f"model-{i}b",
                    downloads=100_000,
                ),
                _hf(params_total=i * 1_000_000_000),
                existing_ids=set(),
            )
            for i in range(1, 4)
        ]
        assert all(s is not None for s in seeds)

        blocks = "".join(seed_to_yaml_block(s) for s in seeds)  # type: ignore[arg-type]
        seed_file = tmp_path / "multi-seed.yaml"
        seed_file.write_text(f"models:\n{blocks}", encoding="utf-8")

        loaded = load_model_seed(seed_file)
        assert len(loaded) == 3
        assert loaded[0].id == "model-1b"
        assert loaded[2].id == "model-3b"

    def test_round_trip_with_yaml_special_chars(self, tmp_path: Path) -> None:
        """YAML special chars in license and use_case round-trip correctly."""
        # Create a seed with YAML-special chars: colons, spaces
        seed = ModelSeed(
            id="test-special-chars",
            name="Test Model Special",
            family="Test",
            hf_repo="test-org/Test-Model-7B",
            params_total=7_000_000_000,
            license="custom: see the model card",
            use_case="chat: general, coding",
            backer=None,
            modality=None,
            openness=None,
            release_date=None,
        )

        block = seed_to_yaml_block(seed)
        yaml_content = f"models:\n{block}"
        seed_file = tmp_path / "model-seed-special.yaml"
        seed_file.write_text(yaml_content, encoding="utf-8")

        # Load and verify the YAML is valid and values are preserved exactly
        loaded = load_model_seed(seed_file)
        assert len(loaded) == 1
        loaded_seed = loaded[0]
        assert loaded_seed.id == "test-special-chars"
        assert loaded_seed.license == "custom: see the model card"
        assert loaded_seed.use_case == "chat: general, coding"
        assert loaded_seed.family == "Test"
        assert loaded_seed.name == "Test Model Special"
