# Contributing

Thanks for your interest in AI Radar Pulse. This project is licensed under the
[MIT License](LICENSE); contributions are accepted under the same license.

## Development setup

Requires Python 3.12+, [uv](https://github.com/astral-sh/uv) and Node 20.

```bash
uv sync                          # package + dev tools
uv run pytest --cov              # Python suite (offline: every network call is mocked)
npm ci --prefix frontend && npm test --prefix frontend
uv run radar pulse --help        # the CLI
```

## Principles

- **Pulse is self-contained.** Nothing under `src/radar/pulse/` imports from
  outside it. Dependencies point one way: sources → pipeline → triage/rank →
  view → export/telegram.
- **`data/pulse.v1.json` is the contract.** The site, RSS and the homelab
  worker read it; `view.validate_view` pins the schema. Change it only with a
  new schema version.
- **Failures are visible.** A source error is recorded per request in
  `data/pulse/health.json` and shown on the site; a Jev outage falls back to
  rules and says so. Never swallow an error silently.
- **Immutable data flow.** Functions return new objects; they don't mutate inputs.
- **Secrets never leave the environment.** Read them through `radar.pulse.env`;
  never log or print them (the Telegram token is scrubbed from errors, tested).

## Adding a source

Most additions need no code: add a feed to `news.sources`, a topic to
`repos.topics` or a lab org to `models.lab_orgs` in `config/pulse.yaml`.
A new kind of source is a module in `src/radar/pulse/sources/` that returns a
`SourceRun`, plus one line in `pipeline.collect`.

## Commits & branches

- Branch from `main`: `feature/<scope>/<desc>`, `fix/<scope>/<desc>`,
  `refactor/<desc>` or `chore/<desc>`. Don't commit directly to `main`.
- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`,
  `refactor:`, `docs:`, `test:`, `chore:`, `perf:`, `ci:`.
- Open a PR with a summary and a test plan. CI runs both suites and the
  browser checks on every PR.
