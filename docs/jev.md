# How the radar uses Jev

[Jev](https://typesafe.ai) (TypeSafe AI, released 2026-09-15) is the
classifier behind Radar Pulse. This page covers what we ask it, how the
answers turn into a ranking, what it costs, what happens when it is down, and
how to change it safely. For the whole pipeline see [pulse.md](pulse.md).

## What Jev is, in one paragraph

Jev is a "System One" model. It never writes text. You describe the possible
answers up front and it returns a **typed decision with calibrated
probabilities**:

| Question type | Returns | Example use here |
|---|---|---|
| `choice` | one option out of 2–255, with a probability per option and a `confidence` | "what kind of event is this article?" |
| `noul` | a 0–1 probability that a statement is true | "does this paper release code or weights?" |
| `score` | a position on an ordered 2–10 level rubric | not used (see "facts, not taste") |

It is API-only (`POST https://api.typesafe.ai/v1/systemone`, model
`jev-latest`, `Authorization: Bearer $TYPESAFE_API_KEY`). One call can carry
several questions about the same input. Pricing is **$0.042 per million
input tokens**; output is free.

## Why a classifier, and why Jev

The radar never had a collection problem. In two weeks it gathered about 10,000
new Hugging Face repos, hundreds of news items and a hundred papers a day. What
it lacked was triage: which of these is a real release, a paper worth reading,
a usable tool, or just noise? That is a classification job, not a writing job,
and Jev is built for exactly that: cheap, fast (70–600 ms), and it returns
probabilities we can threshold on.

## Facts, not taste

The design rule, learned from the first live call (2026-09-30):

| Question asked | GPT-6.1 Sol launch | Airbnb customer story |
|---|---|---|
| "Would a developer regret missing this?" (subjective) | 0.33 | 0.34 |
| "What kind of event is this?" (factual) | `model-release`, confidence **1.00** | `policy-business`, 0.83 |

Jev is excellent at *what something is* and cannot tell *how much you
care*. So we only ask it facts. **Importance is computed by readable rules**
in `src/radar/pulse/rank.py` from those facts plus hard signals (likes,
upvotes, stars/day, source authority). Every ranked item carries the reasons
for its position, so an odd ranking is debuggable instead of mysterious.

## The questions

All questions live in [`config/pulse-questions.yaml`](../config/pulse-questions.yaml).
They are provider-agnostic: the same file drives Jev and the fallback rules.
The file carries a `version`, and labels are cached per version.

| Lane | Key | Type | Options | Asked for |
|---|---|---|---|---|
| news | `event` | choice | `model-release`, `tool-release`, `research`, `benchmark`, `security`, `tutorial-opinion`, `business-policy`, `customer-story`, `unrelated` | every news item |
| repo | `kind` | choice | `tool`, `framework`, `model`, `app-demo`, `list-course`, `other` | every new repo |
| paper | `topic` | choice | `inference-efficiency`, `training`, `agents-tools`, `retrieval`, `multimodal`, `evaluation`, `safety`, `embodied`, `other` | every paper |
| paper | `usable_now` | noul | releases code, weights, a dataset or a tool | every paper |
| model | `new_model` | noul | a genuinely new model vs. a quant/merge/re-upload | **only** models the lineage rules could not settle |

Most models never reach Jev. Hugging Face `base_model` tags, the owning org
and repo-name markers (`GGUF`, `AWQ`, `NVFP4`, `abliterated`…) settle
original / variant / derivative deterministically
(`src/radar/pulse/lineage.py`). Only the `unknown` rest is classified. A
test pins 16 real 2026-08/09 lab releases as original and 9 of their repacks
as not (`tests/test_pulse_k1_acceptance.py`).

## What Jev sees

`item_state()` in `src/radar/pulse/classify.py` builds a short, stable text:

```
Title: Introducing GPT-6.1 Sol
Source: openai-news
URL: https://openai.com/index/introducing-gpt-6-1-sol
Tags: …            (repos: GitHub topics; models: pipeline tag)
Summary: …         (feed summary / paper abstract / repo description, ≤400 chars)
```

Volatile numbers (likes, stars) are deliberately left out, so the text only
changes when the content changes. That keeps the cache valid.

## How an answer becomes a ranking

`src/radar/pulse/rank.py`. Confidence below **0.5** puts an item in the
*uncertain* bucket instead of the main list.

| Lane | Score | Filtered out (shown separately, with the reason) |
|---|---|---|
| news | event weight (model-release 5, tool-release 4, security 4, research 3, benchmark 3, tutorial-opinion 1, business-policy 0.5) × confidence × source authority (official lab blogs 1.3–1.5, practitioners 1.1–1.2, HN >100 points 1.0, unfiltered HN keyword searches 0.6) | `customer-story`, `unrelated` |
| repo | 2 × log10(1 + stars/day) | `app-demo`, `list-course`, `other` (only `tool`, `framework`, `model` rank) |
| paper | 2 × log10(1 + upvotes) + topic bonus (inference-efficiency/agents-tools +1, retrieval/training +0.5) + 1 if `usable_now` ≥ 0.5 | nothing |
| model | 5 (original) or 3 (unknown judged new, `new_model` ≥ 0.5) + log10(1 + likes) + 0.5 × log10(1 + downloads) | variants and derivatives of another release |

Nothing is thrown away. The site and `data/pulse.v1.json` carry every item,
including the uncertain and filtered ones with their reasons (the owner's
standing preference: *"I want all, as much as possible"*).

## Cost, caching and limits

- **Cache**: `data/pulse/labels.jsonl`, keyed by (item id, content hash,
  question version). An item is sent to Jev once. A later rules label never
  overwrites a Jev label for the same content.
- **Budget**: `triage.token_budget_per_run` in `config/pulse.yaml`, default
  **300,000 input tokens per run** (≈ $0.0126). When the budget runs out, the
  rest of the run uses rules and the next run upgrades them.
- **Real numbers**: a cold start of 579 items took 20 s and cost $0.0128. A
  typical 2-hourly run triages 100–200 new items for under half a cent. The
  monthly total stays well under $1.
- **Concurrency**: 8 requests in flight. 429 and 529 ("overloaded") are
  retried with exponential backoff.

## When Jev is unavailable

Pulse never goes silent, and it never pretends:

1. **Rules fallback**. `RulesEngine` (keyword heuristics, confidence 0.3)
   labels anything Jev could not. Those items land in the *uncertain* bucket
   and carry a `rules` badge.
2. **Circuit breaker**. After 5 consecutive Jev failures the run stops calling
   it and uses rules for the rest.
3. **Visible degradation**. If more than half of the shown items were ranked
   without a classifier, the site shows a "Triage degraded" banner, the
   Telegram digest prints a warning line, and the watchdog raises
   `triage-degraded` through Çakır.
4. **Self-healing**. When Jev is back, rules labels are upgraded
   automatically on the next run.
5. **No key**. Without `TYPESAFE_API_KEY`, `radar pulse triage` prints a
   visible warning and uses rules only.

The key is never logged or placed in error messages (tested).

## Where it runs and the key

- GitHub Actions `publish.yml` runs `radar pulse triage` every two hours with
  the repository secret `TYPESAFE_API_KEY`.
- Locally, the key can sit in the git-ignored project `.env`
  (`TYPESAFE_API_KEY=…`), read by the same loader as `HF_TOKEN`.
- The homelab worker does **not** call Jev. It reads the already-triaged
  `pulse.v1.json`.

## How well it works (measured)

- **Silver check** (2026-09-30): 266 news items stratified by type, compared
  with the labels Claude Opus had produced for the older newsroom question
  ("relevant to on-prem operators?"). Result: F1 0.83 at threshold 0.4,
  agreement 79.3%, event-type agreement 63.9% (most disagreement is Claude's
  `other` vs. Jev's `community`, two catch-all buckets). With confidence
  ≥ 0.9, agreement was 79.5% on 48% of the items, so the confidence is
  informative.
- The pre-registered gate (F1 ≥ 0.85 and agreement ≥ 80%) was missed
  narrowly. Those labels answer a different question, though, so they could
  neither reject nor confirm Jev.
- **Decision**: Jev stays the default. The owner found an up-front gold set
  impossible to label in the abstract, so quality is steered by usage
  instead: each "why is X missing?" or "Y is noise" becomes a regression test
  and, if needed, a rule or question change.
- Tooling for a formal comparison remains: `radar pulse gold-sample` writes a
  checklist plus a frozen snapshot, and `radar pulse eval` re-triages that
  snapshot with Jev and with rules and scores each against the owner's ticks.

## Changing the questions safely

1. Edit `config/pulse-questions.yaml`. Keep asking facts.
2. **Bump `version`.** Every item is then re-labeled once. Budget about
   300 tokens per item: the next few runs spread it under the per-run budget.
3. If you add or rename an option, update the matching weights or filters in
   `src/radar/pulse/rank.py` and the `RulesEngine` heuristics in
   `classify.py`. Run the tests; `tests/test_pulse_triage.py` validates the
   shipped question file.
4. Look at the result before merging:
   `radar pulse triage && radar pulse top --lane news --limit 30` (add
   `--show-hidden` to see what was filtered and why).

## Useful commands

```bash
uv run radar pulse collect   # fetch lab models + daily papers, fold in repo/news logs
uv run radar pulse triage    # label new items with Jev (rules fallback), print tokens and cost
uv run radar pulse top --lane news --limit 20             # ranking with reasons
uv run radar pulse top --lane repo --limit 50 --show-hidden
```
