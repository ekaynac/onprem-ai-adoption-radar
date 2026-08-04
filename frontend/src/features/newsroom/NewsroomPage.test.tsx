import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { NewsroomPage } from "./NewsroomPage";


afterEach(() => {
  vi.unstubAllGlobals();
});


function stubSnapshot() {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "1.0",
            generated_at: "2026-08-04T10:00:00Z",
            newsroom: {
              items: [
                {
                  id: "news:break",
                  source_id: "vllm-blog",
                  title: "vLLM drops V0 engine",
                  url: "https://blog.vllm.ai/v0-removal",
                  summary: "V0 removed",
                  published_at: "2026-08-02T09:00:00Z",
                  classification: {
                    event_type: "breaking-change",
                    components: ["vllm"],
                    operational_impact: "breaking",
                    summary:
                      "V0 engine removed; pinned deployments must migrate.",
                    citation: "https://blog.vllm.ai/v0-removal",
                    model: "claude-opus-5",
                  },
                },
                {
                  id: "news:raw",
                  source_id: "hn-ollama",
                  title: "Ask HN: local LLM stack?",
                  url: "https://news.ycombinator.com/item?id=42",
                  summary: "Discussion thread",
                  published_at: "2026-08-03T09:00:00Z",
                  classification: null,
                },
              ],
              counts: {
                total: 2,
                classified: 1,
                unclassified: 1,
                breaking: 1,
                improvement: 0,
                informational: 0,
              },
              event_types: ["release", "breaking-change"],
            },
            projects: [],
            model_candidates: [],
            platforms: [],
            hardware: [],
            research: [],
            models: [],
            releases: [],
            events: [],
            source_health: {
              open_review_count: 0,
              stale_claim_count: 0,
              source_health: [],
            },
          }),
          { status: 200 },
        ),
      ),
    ),
  );
}


function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewsroomPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}


test("shows classified items with impact pill and component chips", async () => {
  stubSnapshot();
  renderPage();

  expect(
    await screen.findByRole("link", { name: "vLLM drops V0 engine" }),
  ).toHaveAttribute("href", "https://blog.vllm.ai/v0-removal");
  const pill = document.querySelector(".verdict-pill.impact-breaking");
  expect(pill).toHaveTextContent("Breaking");
  expect(
    screen.getByText("V0 engine removed; pinned deployments must migrate."),
  ).toBeVisible();
  expect(screen.getByText("breaking-change")).toBeVisible();
  expect(screen.getByText("vllm")).toBeVisible();
  expect(screen.getByLabelText("Newsroom counts")).toHaveTextContent(
    "1 classified · 1 breaking · 1 raw",
  );
  // Default view hides the raw firehose.
  expect(
    screen.queryByText("Ask HN: local LLM stack?"),
  ).not.toBeInTheDocument();
});


test("the raw firehose is reachable and marked unclassified", async () => {
  stubSnapshot();
  renderPage();
  await screen.findByRole("link", { name: "vLLM drops V0 engine" });

  fireEvent.change(screen.getByLabelText("View"), {
    target: { value: "all" },
  });

  expect(
    screen.getByRole("link", { name: "Ask HN: local LLM stack?" }),
  ).toBeVisible();
  expect(screen.getByText("Unclassified")).toBeVisible();
  expect(screen.getByText("Discussion thread")).toBeVisible();
});
