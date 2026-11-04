# Security Policy

## Supported versions

Only the latest `main` branch receives security fixes.

## Reporting a vulnerability

Please open a private GitHub security advisory
(**Security → Report a vulnerability** on the repository) rather than a public
issue. Expect an initial response within 7 days.

## Security model

- **The site is static and public by design.** GitHub Pages serves the built
  frontend, `data/pulse.v1.json` and RSS. There is no server, API or write path.
- **Secrets** (`TYPESAFE_API_KEY`, `HF_TOKEN`, `GITHUB_TOKEN`) live in GitHub
  Actions secrets or a git-ignored `.env`, and reach only the step that
  collects and triages. The Telegram and Claude tokens exist only on the
  homelab worker (`/etc/radar/env`, root:radar 0640).
- **Untrusted input.** Item titles and summaries come from the open internet.
  They are validated at the boundary (pydantic), escaped wherever rendered
  (HTML, RSS, Telegram), and framed as data in the one LLM prompt, which runs
  with every tool disabled and a filtered environment.
- **The homelab worker never pulls code on its own**; updates are deliberate
  (`update-radar`), and data arrives as the published, schema-checked
  `pulse.v1.json`.
