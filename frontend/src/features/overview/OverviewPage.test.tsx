import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { OverviewPage } from "./OverviewPage";


function response(payload: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "content-type": "application/json" },
    }),
  );
}


function renderOverview(staticMode = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <OverviewPage staticMode={staticMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}


afterEach(() => {
  vi.unstubAllGlobals();
});


test("shows detected releases without presenting them as recommendations", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/releases")) {
        return response({
          items: [
            {
              release_id: "release:kimi-k3",
              name: "Kimi K3",
              lifecycle: "detected",
              lane: "deployable_onprem",
              category: "text_reasoning",
              first_observed_at: "2026-07-30T09:48:00Z",
              age_hours: 0.2,
              freshness: "fresh",
              confidence: 0.8,
              review_status: "clear",
              citations: [],
            },
          ],
          next_cursor: null,
        });
      }
      if (url.includes("/catalog")) {
        return response({ items: [], next_cursor: null });
      }
      return response({
        source_health: [],
        open_review_count: 0,
        stale_claim_count: 0,
      });
    }),
  );

  renderOverview();

  expect(await screen.findByText("Kimi K3")).toBeVisible();
  expect(screen.getByText("Detected")).toBeVisible();
  expect(screen.queryByText("Adopt Kimi K3")).not.toBeInTheDocument();
});


test("shows freshness and review exceptions", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/releases") || url.includes("/catalog")) {
        return response({ items: [], next_cursor: null });
      }
      return response({
        source_health: [],
        fresh_claim_pct: 97,
        open_review_count: 3,
        stale_claim_count: 4,
      });
    }),
  );

  renderOverview();

  expect(await screen.findByText("97%")).toBeVisible();
  expect(screen.getByText("4 stale claims")).toBeVisible();
  expect(screen.getByText("3 review exceptions")).toBeVisible();
});


test("counts only explicitly healthy sources with closed circuits", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/releases") || url.includes("/catalog")) {
      return response({ items: [], next_cursor: null });
    }
    return response({
      source_health: [
        { source_id: "ok", status: "ok", consecutive_failures: 0 },
        { source_id: "empty", status: "empty", consecutive_failures: 0 },
        { source_id: "failed", status: "error", consecutive_failures: 2 },
        { source_id: "open", status: "ok", consecutive_failures: 5, circuit_open_until: "2026-08-04T00:00:00Z" },
      ],
      open_review_count: 0,
      stale_claim_count: 0,
    });
  }));

  renderOverview();

  expect(await screen.findByText("2/4 healthy")).toBeVisible();
});


test("static mode labels the generated snapshot without live or estate claims", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/releases") || url.includes("/catalog")) {
      return response({ items: [], next_cursor: null });
    }
    if (url.includes("public-snapshot")) {
      return response({ generated_at: "2026-08-03T08:00:00Z" });
    }
    return response({ source_health: [], open_review_count: 0, stale_claim_count: 0 });
  }));

  renderOverview(true);

  expect(await screen.findByText(/Snapshot generated/)).toBeVisible();
  expect(screen.queryByText(/Live data/)).not.toBeInTheDocument();
  expect(screen.queryByText(/Your estate and policies applied/)).not.toBeInTheDocument();
});
