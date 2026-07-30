"""Architecture-correct KV-cache byte math — the headline fix of the capacity engine.

Dispatch order (spec §6), most-specific geometry first:
1. MLA (kv_lora_rank present) — compressed latent cache, independent of head count.
2. GQA/MHA/HYBRID (num_key_value_heads + head_dim present) — standard per-head cache.
   HYBRID is approximated as full GQA on the published kv geometry (an upper bound;
   real sliding-window layers cost less).
3. No architecture, but num_layers + hidden_size known — legacy MHA upper bound.
4. Nothing known — KV cache is not modeled; callers must not silently guess.

Partial data never silently guesses: an architecture with kv_heads but no head_dim
(or vice versa) falls through to rule 3/4 rather than assuming a value.
"""

from __future__ import annotations

from radar.capacity.types import DTYPE_BYTES
from radar.models_radar.entities import ArchitectureSpec, AttentionKind


def kv_bytes_per_token(
    architecture: ArchitectureSpec | None,
    *,
    num_layers: int | None,
    hidden_size: int | None,
    kv_dtype: str = "fp16",
) -> tuple[float | None, list[str]]:
    """Bytes of KV cache per token, plus assumption notes explaining how it was derived.

    Returns (None, [reason]) when there isn't enough data to model the KV cache at all.
    """
    if kv_dtype not in DTYPE_BYTES:
        raise ValueError(
            f"Unknown kv_dtype {kv_dtype!r} — expected one of {list(DTYPE_BYTES)}"
        )
    dtype_bytes = DTYPE_BYTES[kv_dtype]

    if architecture is not None and num_layers is not None:
        kv_lora_rank = architecture.kv_lora_rank
        if kv_lora_rank is not None:
            # Rule 1: MLA — compressed latent cache wins over any GQA-shaped fields.
            rope_dim = architecture.qk_rope_head_dim or 0
            bytes_per_token = (kv_lora_rank + rope_dim) * dtype_bytes * num_layers
            note = f"KV: MLA latent cache ({kv_lora_rank}+{rope_dim})/layer"
            return bytes_per_token, [note]

        kv_heads = architecture.num_key_value_heads
        head_dim = architecture.head_dim
        if kv_heads is not None and head_dim is not None:
            # Rule 2: GQA/MHA/HYBRID — standard per-head KV cache.
            bytes_per_token = 2 * kv_heads * head_dim * dtype_bytes * num_layers
            notes: list[str] = []
            if architecture.attention_kind is AttentionKind.HYBRID:
                notes.append(
                    "KV: hybrid attention approximated as full GQA on published kv "
                    "geometry — upper bound (sliding-window layers cost less)"
                )
            return bytes_per_token, notes

    if num_layers is not None and hidden_size is not None:
        # Rule 3: no (usable) architecture — legacy MHA upper bound from hidden_size.
        bytes_per_token = 2 * hidden_size * dtype_bytes * num_layers
        return bytes_per_token, ["KV: architecture unknown — MHA upper bound from hidden_size"]

    # Rule 4: nothing known — never silently guess.
    return None, ["KV: no architecture data — KV cache not modeled"]


def kv_gb(bytes_per_token: float, context_tokens: int, concurrent_requests: int = 1) -> float:
    """Total KV-cache size in GB for a given context length and concurrency."""
    return round(bytes_per_token * context_tokens * concurrent_requests / 1e9, 2)
