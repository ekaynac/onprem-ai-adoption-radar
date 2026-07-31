"""Deterministically export the versioned REST contract for frontend types."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from radar.api.app import create_api_app


def export_openapi(root: Path, output: Path) -> Path:
    schema = create_api_app(root, read_only=True).openapi()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(schema, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        "--out",
        type=Path,
        default=Path("build/openapi.json"),
    )
    args = parser.parse_args()
    export_openapi(args.root, args.output)


if __name__ == "__main__":
    main()
