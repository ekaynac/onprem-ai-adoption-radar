import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { ReleaseStreamPage } from "./ReleaseStreamPage";


afterEach(() => {
  vi.unstubAllGlobals();
});


test("filters the release stream by lifecycle", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
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
              {
                release_id: "release:verified-model",
                name: "Verified Model",
                lifecycle: "verified",
                lane: "onprem_adjacent",
                category: "multimodal",
                first_observed_at: "2026-07-29T09:48:00Z",
                age_hours: 24,
                freshness: "fresh",
                confidence: 0.95,
                review_status: "clear",
                citations: [],
              },
            ],
            next_cursor: null,
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
        <ReleaseStreamPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Kimi K3")).toBeVisible();
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Lifecycle" }),
    "verified",
  );

  expect(screen.queryByText("Kimi K3")).not.toBeInTheDocument();
  expect(screen.getByText("Verified Model")).toBeVisible();
});


test("shows older releases by default instead of opening on an empty stream", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            items: [
              {
                release_id: "release:older",
                name: "Older Release",
                lifecycle: "detected",
                lane: "onprem_adjacent",
                category: "text_reasoning",
                first_observed_at: "2026-06-01T00:00:00Z",
                age_hours: 1440,
                freshness: "stale",
                confidence: 0.8,
                review_status: "clear",
                citations: [],
              },
            ],
            next_cursor: null,
          }),
          { status: 200 },
        ),
      ),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ReleaseStreamPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Older Release")).toBeVisible();
  expect(screen.getByRole("combobox", { name: "Age" })).toHaveValue("all");
});
