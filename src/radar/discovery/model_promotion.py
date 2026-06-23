"""Promotion logic: filter discovered ModelProposals → ModelSeed candidates.

Quality-gate rules decide which HF proposals are good enough to promote into
the model seed catalog.  Nothing here touches the file system or network; all
I/O lives at the call site.
"""

from __future__ import annotations

import re

from radar.discovery.model_proposals import ModelProposal
from radar.models import Backer, BackerType
from radar.models_radar.assemble import openness_from_license
from radar.models_radar.collectors.huggingface import HFModelData
from radar.models_radar.entities import Modality, ModelSeed


# ---------------------------------------------------------------------------
# Backer lookup table
# ---------------------------------------------------------------------------

_ORG_BACKER: dict[str, Backer] = {
    "qwen": Backer(name="Alibaba", type=BackerType.BIG_TECH),
    "meta-llama": Backer(name="Meta", type=BackerType.BIG_TECH),
    "mistralai": Backer(name="Mistral AI", type=BackerType.STARTUP),
    "google": Backer(name="Google", type=BackerType.BIG_TECH),
    "microsoft": Backer(name="Microsoft", type=BackerType.BIG_TECH),
    "deepseek-ai": Backer(name="DeepSeek", type=BackerType.STARTUP),
    "cohereforai": Backer(name="Cohere", type=BackerType.STARTUP),
    "coherelabs": Backer(name="Cohere", type=BackerType.STARTUP),
    "01-ai": Backer(name="01.AI", type=BackerType.STARTUP),
    "ibm-granite": Backer(name="IBM", type=BackerType.BIG_TECH),
    "huggingfacetb": Backer(name="Hugging Face", type=BackerType.COMMUNITY),
    "bigcode": Backer(name="BigCode", type=BackerType.COMMUNITY),
    "nvidia": Backer(name="NVIDIA", type=BackerType.BIG_TECH),
    "allenai": Backer(name="AllenAI", type=BackerType.ACADEMIC),
}


def backer_for_org(org: str) -> Backer:
    """Return the known Backer for a HF org name (case-insensitive).

    Falls back to a COMMUNITY backer with the org name when not in the table.
    """
    return _ORG_BACKER.get(org.lower(), Backer(name=org, type=BackerType.COMMUNITY))


# ---------------------------------------------------------------------------
# Quality-gate constants
# ---------------------------------------------------------------------------

_DERIVATIVE_RE = re.compile(
    r"gguf|awq|gptq|exl2|-bnb|fp8|int4|int8|-4bit|-8bit|-mlx|-quantized|-lora|-adapter",
    re.IGNORECASE,
)

_REPUBLISHER_ORGS: frozenset[str] = frozenset(
    {
        "thebloke",
        "unsloth",
        "bartowski",
        "mradermacher",
        "quantfactory",
        "lmstudio-community",
        "second-state",
        "richarderkhov",
        "devquasar",
    }
)


def is_promotable(
    proposal: ModelProposal,
    *,
    min_downloads: int,
    seeded_repos: set[str],
) -> bool:
    """Return True iff *proposal* passes all quality-gate checks.

    ALL conditions must hold:
    - hf_repo not already seeded (case-insensitive)
    - downloads >= min_downloads
    - repo name does not match derivative/quant patterns
    - org (before '/' in hf_repo) is not a known republisher
    - modality is text or multimodal
    """
    repo = proposal.hf_repo
    org = repo.split("/")[0].lower()

    if repo.lower() in seeded_repos:
        return False
    if proposal.downloads < min_downloads:
        return False
    if _DERIVATIVE_RE.search(repo):
        return False
    if org in _REPUBLISHER_ORGS:
        return False
    return proposal.modality in {"text", "multimodal"}


# ---------------------------------------------------------------------------
# Family derivation
# ---------------------------------------------------------------------------

_SIZE_TOKEN_RE = re.compile(r"^\d+\.?\d*[bBmM]$")
_VARIANT_WORDS = frozenset({"instruct", "chat", "it", "base"})


def derive_family(name: str) -> str:
    """Strip trailing size/variant tokens from a model name to get its family.

    Examples:
        Qwen3-0.6B          → Qwen3
        Llama-3.1-8B-Instruct → Llama-3.1
        Gemma-3-12B-IT      → Gemma-3
        Mistral-7B          → Mistral
    """
    # Split on common separators, keeping the separator context by splitting on
    # the whole name using '-' or space as a delimiter.
    # We work with '-' separated tokens (most HF names use '-').
    parts = name.split("-")
    while parts:
        last = parts[-1]
        if _SIZE_TOKEN_RE.match(last) or last.lower() in _VARIANT_WORDS:
            parts = parts[:-1]
            # If we stripped everything, stop to preserve original
            if not parts:
                return name
        else:
            break

    result = "-".join(parts)
    # Strip any trailing separator
    result = result.rstrip("-")
    return result if result else name


# ---------------------------------------------------------------------------
# Seed builder
# ---------------------------------------------------------------------------

_MODALITY_MAP: dict[str, Modality] = {
    "text": Modality.TEXT,
    "multimodal": Modality.MULTIMODAL,
    "vision": Modality.VISION,
    "audio": Modality.AUDIO,
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}")


def build_seed(
    proposal: ModelProposal,
    hf: HFModelData | None,
    *,
    existing_ids: set[str],
) -> ModelSeed | None:
    """Construct a ModelSeed from a proposal + HF API data.

    Returns None when:
    - hf is None (no network data available)
    - hf.params_total is None (can't produce a useful seed without size)
    - no unique ID can be generated within 50 attempts
    """
    if hf is None or hf.params_total is None:
        return None

    # Resolve unique ID
    base_id = proposal.suggested_id
    candidate = base_id
    for attempt in range(2, 52):
        if candidate not in existing_ids:
            break
        candidate = f"{base_id}-{attempt}"
    else:
        return None  # all 50 slots taken

    # Family: use derive_family unless it returns the original (no strip) and
    # proposal.family is non-empty, in which case use the proposal's value.
    derived = derive_family(proposal.name)
    family = derived if derived != proposal.name else (proposal.family or derived)

    # Modality
    modality: Modality = _MODALITY_MAP.get(proposal.modality, Modality.TEXT)

    # Release date: use last_modified[:7] when it looks like a date
    release_date: str | None = None
    if hf.last_modified and _DATE_RE.match(hf.last_modified):
        release_date = hf.last_modified[:7]

    # Backer from the HF org
    org = proposal.hf_repo.split("/")[0]
    backer = backer_for_org(org)

    return ModelSeed(
        id=candidate,
        name=proposal.name,
        family=family,
        hf_repo=proposal.hf_repo,
        ollama_name=None,
        backer=backer,
        params_total=hf.params_total,
        params_active=None,
        num_layers=hf.num_layers,
        hidden_size=hf.hidden_size,
        context_length=hf.context_length,
        modality=modality,
        license=hf.license,
        openness=openness_from_license(hf.license),
        release_date=release_date,
        use_case=None,
    )


# ---------------------------------------------------------------------------
# YAML serialiser
# ---------------------------------------------------------------------------


def seed_to_yaml_block(seed: ModelSeed) -> str:
    """Render one ModelSeed as a hand-authored-style YAML list item.

    Matches the style of config/model-seed.yaml:
    - 2-space indent: ``  - id: ...`` then ``    key: value``
    - inline backer: ``    backer: {name: "X", type: big_tech}``
    - only non-None optional fields are emitted
    - enum fields use ``.value``
    """
    lines: list[str] = []
    lines.append(f"  - id: {seed.id}")
    lines.append(f"    name: {seed.name}")
    lines.append(f"    family: {seed.family}")
    if seed.hf_repo is not None:
        lines.append(f"    hf_repo: {seed.hf_repo}")
    if seed.ollama_name is not None:
        lines.append(f"    ollama_name: {seed.ollama_name}")
    if seed.backer is not None:
        lines.append(
            f'    backer: {{name: "{seed.backer.name}", type: {seed.backer.type.value}}}'
        )
    if seed.params_total is not None:
        lines.append(f"    params_total: {seed.params_total}")
    if seed.params_active is not None:
        lines.append(f"    params_active: {seed.params_active}")
    if seed.num_layers is not None:
        lines.append(f"    num_layers: {seed.num_layers}")
    if seed.hidden_size is not None:
        lines.append(f"    hidden_size: {seed.hidden_size}")
    if seed.context_length is not None:
        lines.append(f"    context_length: {seed.context_length}")
    if seed.modality is not None:
        lines.append(f"    modality: {seed.modality.value}")
    if seed.license is not None:
        lines.append(f"    license: {seed.license}")
    if seed.openness is not None:
        lines.append(f"    openness: {seed.openness.value}")
    if seed.release_date is not None:
        lines.append(f'    release_date: "{seed.release_date}"')
    if seed.use_case is not None:
        lines.append(f"    use_case: {seed.use_case}")
    lines.append("")  # trailing newline / blank separator
    return "\n".join(lines)
