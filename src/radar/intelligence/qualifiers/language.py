"""Text, reasoning, and multimodal language-model qualification."""

from __future__ import annotations

from radar.intelligence.contracts import Claim, Release
from radar.intelligence.qualifiers.base import PredicateQualifier
from radar.models_radar.memory import estimate_memory_gb


class LanguageQualifier(PredicateQualifier):
    required_predicates = ("params_total",)
    fit_metrics = ("memory_gb_4bit", "context_length")
    risk_checks = ("license", "gating", "remote_code")

    def reasons(
        self,
        release: Release,
        claims: dict[str, Claim],
    ) -> list[str]:
        params = _integer_claim(claims, "params_total")
        context = _integer_claim(claims, "context_length") or 4096
        memory = estimate_memory_gb(
            params,
            bits_per_weight=4.0,
            context=context,
            num_layers=_integer_claim(claims, "num_layers"),
            hidden_size=_integer_claim(claims, "hidden_size"),
        )
        if memory is None:
            return ["Memory fit could not be calculated from verified claims"]
        return [
            f"Estimated 4-bit memory footprint: {memory:.2f} GB "
            f"at {context} tokens"
        ]

    def assumptions(self, claims: dict[str, Claim]) -> list[str]:
        assumptions = ["4-bit weight estimate with fp16 KV cache"]
        if "context_length" not in claims:
            assumptions.append("Context length defaults to 4096 tokens")
        return assumptions


def _integer_claim(claims: dict[str, Claim], predicate: str) -> int | None:
    claim = claims.get(predicate)
    if claim is None or isinstance(claim.value, bool):
        return None
    if isinstance(claim.value, int):
        return claim.value
    if isinstance(claim.value, str) and claim.value.isdigit():
        return int(claim.value)
    return None
