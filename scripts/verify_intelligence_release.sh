#!/usr/bin/env bash
set -euo pipefail

uv run pytest --cov
uv run ruff check src tests
uv run mypy src/radar
uv run radar intelligence-migrate --root .
uv run radar intelligence-replay-events --root .
uv run radar intelligence-shadow --root . --check
uv run radar export --root . --out _site

(
  cd frontend
  npm ci
  npm run generate:api
  git diff --exit-code -- src/api/generated
  npm test
  npm run typecheck
  npm run lint
  npm run build
  npx playwright test
)
