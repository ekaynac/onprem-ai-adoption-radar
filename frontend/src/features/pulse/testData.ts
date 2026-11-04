import type { PulseRow, PulseView } from "./pulseQueries";


export const GENERATED = "2026-09-30T12:00:00Z";

export function row(id: string, overrides: Partial<PulseRow> = {}): PulseRow {
  return {
    id,
    lane: "news",
    title: `Item ${id}`,
    url: `https://example.com/${id}`,
    source: "openai-news",
    published_at: GENERATED,
    first_seen: GENERATED,
    summary: null,
    kind: null,
    parent: null,
    score: 5,
    bucket: "top",
    reasons: ["model-release (1.00)", "openai-news x1.5"],
    engine: "jev",
    ...overrides,
  };
}

export function view(overrides: Partial<PulseView> = {}): PulseView {
  const news = Array.from({ length: 20 }, (_, i) => row(`news:${i}`));
  news[0] = row("news:0", { title: "Introducing GPT-6.1 Sol" });
  news[19] = row("news:19", { first_seen: "2026-09-20T12:00:00Z", title: "Old news" });
  return {
    schema_version: "pulse-v1",
    generated_at: GENERATED,
    lanes: [
      {
        lane: "model", title: "New models", total: 1, hidden_count: 0, uncertain: [], hidden: [],
        items: [row("model:XiaomiMiMo/MiMo-V2.6-Pro-RL", {
          lane: "model", title: "XiaomiMiMo/MiMo-V2.6-Pro-RL", engine: null,
          reasons: ["original", "603 likes, 78135 downloads"],
        })],
      },
      { lane: "paper", title: "Papers", total: 0, hidden_count: 0, items: [], uncertain: [], hidden: [] },
      { lane: "repo", title: "Repositories", total: 0, hidden_count: 0, items: [], uncertain: [], hidden: [] },
      {
        lane: "news", title: "News", total: 22, hidden_count: 1,
        items: news,
        uncertain: [row("news:u", { bucket: "uncertain", title: "Maybe a release" })],
        hidden: [row("news:h", { bucket: "hidden", title: "Airbnb widens access", reasons: ["customer-story"] })],
      },
    ],
    health: {
      sources: [{ source: "huggingface:lab-models", status: "ok", count: 586, observed_at: GENERATED }],
      engines: { jev: 20 },
      degraded: false,
    },
    ...overrides,
  };
}
