# Contributing

Thanks for your interest in the On-Prem AI Adoption Radar. This project is in the
public domain ([The Unlicense](LICENSE)) — contributions are welcome and become
public domain too.

## Development setup

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv venv && uv pip install -e ".[dev]"
uv run pytest          # run the suite
uv run radar --help    # explore the CLI
```

## Principles

These are load-bearing — please keep them when contributing:

- **Deterministic core.** The default scan path has no LLM and no network beyond
  fetching sources. Anything LLM-based is opt-in, off by default, and degrades to
  the deterministic result on failure.
- **Immutable data flow.** Functions return new objects; they don't mutate inputs.
- **Small, focused modules.** One concern per file; prefer many small files over
  large ones.
- **Test-driven.** Write a failing test first, then the implementation. Keep the
  suite green and meaningful.
- **No silent truncation.** If something is dropped, capped, or sampled, surface
  the count (logs, run meta, or output).

## Tests

- All behavior changes need tests. Run `uv run pytest` before opening a PR.
- Unit-test pure logic directly; integration-test the orchestrator with a
  temporary project root (`initialize_project(tmp_path)`).
- Network and LLM calls are kept behind injectable seams so tests stay offline.

## Adding a source

Most "add a project" requests don't need code — add it to
`config/seed-sources.yaml`, or use `radar seed add …` / the dashboard's
`/sources` form. See the README for the source schema (`github_repo`, `rss`,
`manual`, plus `firehose` and `aliases` for feeds).

## Commits & branches

- Branch from `main`: `feature/<scope>/<desc>`, `fix/<scope>/<desc>`, or
  `chore/<desc>`. Don't commit directly to `main`.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
  `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`.
- Open a PR with a clear summary and a test plan. CI runs the suite on every PR.

## Reporting bugs / ideas

Use the issue templates. For a bug, include the command you ran, what you
expected, and what happened (with any `data/runs/<id>/meta.json` warning).
