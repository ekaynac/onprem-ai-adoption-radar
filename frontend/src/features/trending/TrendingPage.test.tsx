import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { TrendingPage } from "./TrendingPage";


afterEach(() => {
  vi.unstubAllGlobals();
});


test("renders windowed star velocity with NEW flags and sparklines", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "1.0",
            generated_at: "2026-08-12T12:00:00Z",
            trending: {
              sparkline_days: 14,
              windows: {
                "7d": [
                  {
                    repo: "acme/fast-llm",
                    lane: "onprem",
                    stars: 1600,
                    velocity_per_day: 214.3,
                    is_new: true,
                    first_seen: "2026-08-01",
                    description: "Fast local inference",
                    topics: ["llm"],
                    license: "MIT",
                    url: "https://github.com/acme/fast-llm",
                  },
                  {
                    repo: "other/broader-tool",
                    lane: "broader",
                    stars: 900,
                    velocity_per_day: 50,
                    is_new: false,
                    first_seen: "2026-07-10",
                    description: "",
                    topics: [],
                    license: null,
                    url: "https://github.com/other/broader-tool",
                  },
                ],
                "30d": [],
                "90d": [],
              },
              series: {
                "acme/fast-llm": [
                  { observed_at: "2026-08-01T08:00:00Z", stars: 100 },
                  { observed_at: "2026-08-12T08:00:00Z", stars: 1600 },
                ],
              },
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
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <TrendingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("acme/fast-llm")).toBeVisible();
  expect(screen.getByText("NEW")).toBeVisible();
  expect(screen.getByText("+214.3")).toBeVisible();
  expect(
    screen.getByRole("img", { name: "acme/fast-llm star history" }),
  ).toBeVisible();

  // Lane filter narrows to on-prem only.
  await user.selectOptions(screen.getByLabelText("Lane"), "onprem");
  expect(screen.queryByText("other/broader-tool")).not.toBeInTheDocument();

  // Empty window shows the honest empty state.
  await user.selectOptions(screen.getByLabelText("Window"), "30d");
  expect(
    screen.getByText("No trending observations for this view"),
  ).toBeVisible();
});
