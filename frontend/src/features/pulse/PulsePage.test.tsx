import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { PulsePage } from "./PulsePage";
import type { PulseRow, PulseView } from "./pulseQueries";


afterEach(() => {
  vi.unstubAllGlobals();
});


const GENERATED = "2026-09-30T12:00:00Z";

function row(id: string, overrides: Partial<PulseRow> = {}): PulseRow {
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

function view(overrides: Partial<PulseView> = {}): PulseView {
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

function renderWith(data: PulseView | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        data ? new Response(JSON.stringify(data)) : new Response("nope", { status: 500 }),
      ),
    ),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PulsePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}


test("renders every lane with reasons, and the lab launch first", async () => {
  renderWith(view());

  const news = await screen.findByRole("region", { name: /News/ });
  const items = within(news).getAllByRole("listitem");
  expect(items[0]).toHaveTextContent("Introducing GPT-6.1 Sol");
  expect(items[0]).toHaveTextContent("model-release (1.00) · openai-news x1.5");
  expect(screen.getByRole("heading", { name: "New models (1)" })).toBeVisible();
  expect(screen.getByText("XiaomiMiMo/MiMo-V2.6-Pro-RL")).toBeVisible();
  expect(screen.getAllByText("Nothing new in this period")).toHaveLength(2);
});


test("shows the first 15 and reveals all on request, filtered items included", async () => {
  renderWith(view());

  const news = await screen.findByRole("region", { name: /News/ });
  // 19 of 20 are inside the default 7-day window.
  expect(within(news).getAllByRole("listitem").filter((li) => li.closest("ol"))).toHaveLength(15);
  fireEvent.click(within(news).getByRole("button", { name: "Show all 19" }));
  expect(within(news).getAllByRole("listitem").filter((li) => li.closest("ol"))).toHaveLength(19);
  expect(within(news).getByText("1 item(s) filtered out, with the reason for each")).toBeInTheDocument();
  expect(within(news).getByText("Airbnb widens access")).toBeInTheDocument();
  expect(within(news).getByText("1 item(s) the classifier was unsure about")).toBeInTheDocument();
});


test("the period filter widens to everything in the window", async () => {
  renderWith(view());

  await screen.findByRole("region", { name: /News/ });
  fireEvent.change(screen.getByLabelText("Period"), { target: { value: "all" } });
  fireEvent.click(screen.getByRole("button", { name: "Show all 20" }));
  expect(screen.getByText("Old news")).toBeVisible();
});


test("degraded triage and failing sources are announced, never silent", async () => {
  renderWith(view({
    health: {
      sources: [{ source: "huggingface:daily-papers", status: "error", count: 0, observed_at: GENERATED }],
      engines: { rules: 20 },
      degraded: true,
    },
  }));

  const status = await screen.findByRole("status");
  expect(status).toHaveTextContent("Triage degraded");
  expect(status).toHaveTextContent("huggingface:daily-papers: error (0 items)");
});


test("a missing pulse file shows an explicit error", async () => {
  renderWith(null);

  expect(await screen.findByRole("alert")).toHaveTextContent("Pulse is unavailable right now");
});
