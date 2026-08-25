"""Shared console/logger/constants for the CLI command modules."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console


logger = logging.getLogger(__name__)

console = Console()

# The packaged-config fallback root (repo checkout / packaging root that
# carries ``config/``). The old cli.py used ``Path(__file__).resolve()
# .parents[2]``; these modules live one directory deeper (src/radar/cli/), so
# it is parents[3] here — same resolved path as before the split.
BUNDLED_ROOT = Path(__file__).resolve().parents[3]
