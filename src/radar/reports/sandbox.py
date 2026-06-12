"""Per-tool sandbox evaluation plans.

Turns a decision card into a concrete, disposable way to try the tool safely:
a throwaway container or ephemeral environment, minimal permissions, and a
clean teardown. The strategy is inferred deterministically from the card's
tags — no scan, no LLM. This makes "Try This Week" actionable without exposing
the host to an unevaluated agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from radar.models import DecisionCard

_DOCKER_TAGS = {"docker", "self-hosted", "single-binary", "model-serving"}
_NODE_TAGS = {"npm", "node", "vscode-extension"}
_PYTHON_CLI_TAGS = {"cli", "open-source", "coding-agent"}
_DANGEROUS_TAGS = {
    "terminal-access",
    "file-write-access",
    "persistent-agent",
    "browser-access",
}


@dataclass(frozen=True)
class SandboxPlan:
    """A disposable evaluation recipe for one tool."""

    project: str
    strategy: str
    steps: list[str] = field(default_factory=list)
    teardown: list[str] = field(default_factory=list)
    cautions: list[str] = field(default_factory=list)


def build_sandbox_plan(card: DecisionCard) -> SandboxPlan:
    """Infer a safe, disposable trial recipe from a card's tags."""
    tags = {t.lower() for t in card.tags}
    strategy, steps, teardown = _strategy(card.project, tags)
    return SandboxPlan(
        project=card.project,
        strategy=strategy,
        steps=steps,
        teardown=teardown,
        cautions=_cautions(tags),
    )


def _strategy(project: str, tags: set[str]) -> tuple[str, list[str], list[str]]:
    slug = project.lower().replace(" ", "-")
    if tags & _DOCKER_TAGS:
        return (
            "docker",
            [
                f"mkdir -p /tmp/radar-trial-{slug} && cd /tmp/radar-trial-{slug}",
                "# Run in a throwaway container with NO host mounts and a memory cap:",
                f"docker run --rm -it --network none --memory 4g --name trial-{slug} \\",
                "    <image> # replace with the project's published image",
                "# Add ports/GPU/network only once you have read what the tool does.",
            ],
            [
                f"docker rm -f trial-{slug} 2>/dev/null || true",
                f"rm -rf /tmp/radar-trial-{slug}",
            ],
        )
    if tags & _NODE_TAGS:
        return (
            "node-cli",
            [
                f"mkdir -p /tmp/radar-trial-{slug} && cd /tmp/radar-trial-{slug}",
                "# Use a disposable prefix so nothing lands in your global modules:",
                "npm_config_prefix=$PWD/.npm npx --yes <package> # replace package",
            ],
            [f"rm -rf /tmp/radar-trial-{slug}"],
        )
    if tags & _PYTHON_CLI_TAGS:
        return (
            "python-cli",
            [
                f"mkdir -p /tmp/radar-trial-{slug} && cd /tmp/radar-trial-{slug}",
                "python -m venv .venv && . .venv/bin/activate",
                "# Or, for a fully throwaway run: uvx <package>",
                "pip install <package> # replace with the project's package",
            ],
            [
                "deactivate 2>/dev/null || true",
                f"rm -rf /tmp/radar-trial-{slug}",
            ],
        )
    return (
        "manual",
        [
            f"mkdir -p /tmp/radar-trial-{slug} && cd /tmp/radar-trial-{slug}",
            "# No packaged install detected — read the project's docs and run it",
            "# inside a VM or disposable container before touching real data.",
        ],
        [f"rm -rf /tmp/radar-trial-{slug}"],
    )


def _cautions(tags: set[str]) -> list[str]:
    cautions: list[str] = [
        "Trial on disposable data only — never point it at production secrets.",
        "Keep network egress off (or allow-list) until you trust the tool.",
    ]
    dangerous = sorted(tags & _DANGEROUS_TAGS)
    if dangerous:
        cautions.append(
            "Grant minimal permissions: this tool requests "
            + ", ".join(dangerous)
            + " — run without host mounts and review each action."
        )
    if "gpu-required" in tags:
        cautions.append(
            "Needs a GPU: add `--gpus all` only after verifying the image source."
        )
    return cautions


def render_sandbox_markdown(card: DecisionCard, plan: SandboxPlan) -> str:
    """Render a sandbox plan as Markdown."""
    lines = [
        f"# Sandbox trial: {card.project}",
        "",
        f"- **Ring:** `{card.ring.value}`  ·  **Risk:** `{card.risk_level}`  "
        f"·  **Strategy:** {plan.strategy}",
        "",
        "## Cautions",
    ]
    lines.extend(f"- {c}" for c in plan.cautions)
    lines.extend(["", "## Steps", "", "```bash"])
    lines.extend(plan.steps)
    lines.extend(["```", "", "## Teardown", "", "```bash"])
    lines.extend(plan.teardown)
    lines.append("```")
    return "\n".join(lines) + "\n"
