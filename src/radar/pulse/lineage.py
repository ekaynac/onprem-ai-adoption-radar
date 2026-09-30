"""Deterministic model-origin triage: is a new Hub repo a lab release or a copy?

Two weeks of Hub traffic held ~10k new repos, almost all quants, GGUF packs,
merges and re-uploads of a few dozen real releases. Hugging Face ``base_model``
tags settle most of them without a model; repo-name format markers settle most
of the rest. Whatever stays ``UNKNOWN`` is the only part that needs a
classifier (Jev) at all.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ModelOrigin(StrEnum):
    ORIGINAL = "original"  # a new release from the lab that owns the repo
    VARIANT = "variant"  # the lab's own quant/format/adapter of its release
    DERIVATIVE = "derivative"  # someone else's quant, fine-tune, merge or re-upload
    UNKNOWN = "unknown"  # not provable either way; left for the classifier


@dataclass(frozen=True)
class OriginVerdict:
    origin: ModelOrigin
    parent: str | None = None
    reason: str = ""


_BASE_MODEL_PREFIX = "base_model:"
_RELATIONS = frozenset({"quantized", "finetune", "adapter", "merge"})
_COPY_RELATIONS = frozenset({"quantized", "adapter", "merge"})

# Repo-name tokens that mark a repack rather than a new model. Matched on
# token boundaries so "Spark" or "Exp" in a real model name never trips it.
_FORMAT_MARKER = re.compile(
    r"(?:^|[-_.])("
    r"gguf|ggml|awq|gptq|exl2|exl3|mlx|onnx|openvino|bnb|"
    r"fp8|fp4|nvfp4|mxfp4|mxfp|int4|int8|w4a16|w8a8|"
    r"\d+(?:\.\d+)?bpw|[2-8]bit|"
    r"abliterated|heretic|uncensored|lora|qlora|merge|merged|"
    r"gsq|rco|reap\d*|dspark|dflash"
    r")(?=$|[-_.])",
    re.IGNORECASE,
)


def classify_model_origin(
    repo_id: str,
    tags: Iterable[str],
    lab_orgs: frozenset[str],
) -> OriginVerdict:
    """Classify ``repo_id`` from its Hub tags and name; never touches the network."""
    author = repo_id.split("/", 1)[0].casefold()
    labs = frozenset(org.casefold() for org in lab_orgs)
    name = repo_id.split("/", 1)[-1]
    has_marker = _FORMAT_MARKER.search(name) is not None

    base = _base_model(tags)
    if base is not None:
        relation, parent = base
        same_org = parent.split("/", 1)[0].casefold() == author
        if not same_org:
            # A lab training its own model on another lab's base (Apple's
            # LensVLM on Qwen3.5) is a release; a lab repacking one is not.
            if author in labs and relation == "finetune" and not has_marker:
                return OriginVerdict(ModelOrigin.ORIGINAL, parent, f"lab model built on {parent}")
            return OriginVerdict(ModelOrigin.DERIVATIVE, parent, f"{relation} of {parent}")
        if relation in _COPY_RELATIONS or has_marker:
            return OriginVerdict(ModelOrigin.VARIANT, parent, f"own {relation} of {parent}")
        return OriginVerdict(ModelOrigin.ORIGINAL, None, f"own fine-tune of {parent}")

    if author in labs:
        if has_marker:
            return OriginVerdict(ModelOrigin.VARIANT, None, "format marker in lab repo name")
        return OriginVerdict(ModelOrigin.ORIGINAL, None, "lab org, no base model")
    if has_marker:
        return OriginVerdict(ModelOrigin.DERIVATIVE, None, "format marker in repo name")
    return OriginVerdict(ModelOrigin.UNKNOWN, None, "no base model tag or marker")


def _base_model(tags: Iterable[str]) -> tuple[str, str] | None:
    """First ``(relation, parent)`` from ``base_model`` tags; bare tags mean fine-tune."""
    bare: str | None = None
    for tag in tags:
        if not tag.startswith(_BASE_MODEL_PREFIX):
            continue
        rest = tag[len(_BASE_MODEL_PREFIX):]
        relation, _, parent = rest.partition(":")
        if parent and relation in _RELATIONS:
            return relation, parent
        if bare is None and "/" in rest:
            bare = rest
    return ("finetune", bare) if bare is not None else None
