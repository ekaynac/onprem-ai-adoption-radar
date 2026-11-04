# AI Radar Pulse

**New models, papers, repositories and news for an AI developer: collected,
triaged and ranked every two hours, fully unattended.** Open the site, read
the RSS, or get one Telegram message a morning with the top items and a
one-sentence Turkish explanation each.

Built by Enes Kaynakcı (Software Engineer, Mega Bilgisayar) to stay current
while building with AI. The live site is
**<https://ekaynac.github.io/onprem-ai-adoption-radar/>**.

![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![Classifier](https://img.shields.io/badge/triage-Jev%20%2B%20rules%20fallback-blueviolet)
![License](https://img.shields.io/badge/license-MIT-blue)

## What you get

| | |
|---|---|
| 🧠 **New models** | The newest uploads of 30 lab orgs on Hugging Face, with quants, GGUF packs, merges and re-uploads told apart from real releases by `base_model` tags, no model needed ([docs/pulse.md](docs/pulse.md#model-origin-without-a-model)) |
| 📄 **Papers** | Hugging Face daily papers, ranked by upvotes, topic and whether they ship code or weights |
| 🧰 **Repositories** | New GitHub repos by star velocity; lists, courses and demos filtered out, with the reason shown |
| 📰 **News** | Lab blogs (OpenAI, Google DeepMind, Mistral, NVIDIA, Microsoft Research…), practitioners and Hacker News, ranked by what happened × source authority |

- **Triage by [Jev](docs/jev.md).** TypeSafe's classifier answers *facts*
  per item (what kind of event, what kind of repo, paper topic, does it ship
  code). Readable rules turn those facts into a ranking, and every position
  shows its reasons. It costs well under $1 a month. When Jev is down, rules
  take over visibly and upgrade later.
- **Nothing hidden.** The site and `pulse.v1.json` carry every item in the
  14-day window, including uncertain and filtered-out ones with their
  reasons. Ranking only orders items. A failing source is named on the site.
- **Delivered.** The homepage shows four lanes. RSS comes as `pulse.xml` plus
  one feed per lane. The Telegram digest runs daily from a homelab worker via
  the owner's bot, and its Turkish explanations come from Claude on the
  owner's subscription, with every tool disabled.
- **Watched.** A dead-man watchdog alerts once when the site goes stale,
  publish fails twice, a lane empties, a source fails, triage degrades or the
  digest is missing, and once more when the problem clears.

How it works, the code map and the homelab worker:
**[docs/pulse.md](docs/pulse.md)**. How the classifier is used, what it costs
and how to change it: **[docs/jev.md](docs/jev.md)**. Worker setup:
[deploy/homelab/README.md](deploy/homelab/README.md). The rescue plan and
measurements behind all of this (Turkish):
[docs/reports/2026-09-29-radar-rescue-research-and-plan.md](docs/reports/2026-09-29-radar-rescue-research-and-plan.md).

## Run it locally

```bash
uv sync
cp .env.example .env            # optional: TYPESAFE_API_KEY, HF_TOKEN, GITHUB_TOKEN

uv run radar pulse collect      # fetch every source → data/pulse/items.jsonl
uv run radar pulse triage       # Jev labels (rules without a key)
uv run radar pulse top --lane model --limit 20     # the ranking, with reasons

npm ci --prefix frontend && npm run build --prefix frontend
uv run radar pulse export --out _site
python3 -m http.server -d _site 4173               # http://127.0.0.1:4173
```

`data/` is owned by the publish bot: do not commit local changes to it.

## Development

```bash
uv run ruff check src tests && uv run mypy src/radar && uv run pytest --cov
npm test --prefix frontend && npm run typecheck --prefix frontend && npm run lint --prefix frontend
cd frontend && npx playwright test      # against the exported _site
```

Configuration lives in `config/pulse.yaml` (sources, window, budgets,
watchdog) and `config/pulse-questions.yaml` (what Jev is asked). See
[CONTRIBUTING.md](CONTRIBUTING.md).

## History

This repository started as an on-prem AI **adoption radar** and grew an
intelligence platform (catalog, technique radar, capacity planner, MCP
server). Pulse replaced all of it: the old layers were frozen on 2026-09-30
and deleted on 2026-11-04. They are recoverable from the git tag
`pre-slim-2026-11-04`.

## License

MIT. See [LICENSE](LICENSE).
