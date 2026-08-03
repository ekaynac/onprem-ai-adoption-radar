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
  const requested: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      requested.push(String(input));
      return Promise.resolve(
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
      );
    }),
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
  expect(requested.some((url) => url.includes("priority_only"))).toBe(false);
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


test("computes age from the release timestamp instead of frozen snapshot hours", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(new Date("2026-08-03T10:00:00Z"));
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
    items: [{
      release_id: "release:wall-clock",
      name: "Wall Clock Model",
      lifecycle: "detected",
      lane: "onprem_adjacent",
      category: "text_reasoning",
      first_observed_at: "2026-08-02T10:00:00Z",
      age_hours: 0.2,
      freshness: "fresh",
      confidence: 0.8,
      review_status: "clear",
      citations: [],
    }],
    next_cursor: null,
  }), { status: 200 }))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><ReleaseStreamPage /></MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Wall Clock Model")).toBeVisible();
  expect(screen.getByText("24h")).toBeVisible();
  vi.useRealTimers();
});


test("groups derivatives beneath their root and expands on demand", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            items: [
              {
                release_id: "release:grearl:kimi-k3-gguf",
                name: "Kimi K3 GGUF",
                lifecycle: "detected",
                lane: "deployable_onprem",
                category: "multimodal",
                first_observed_at: "2026-08-03T09:00:00Z",
                age_hours: 1,
                freshness: "fresh",
                confidence: 0.75,
                review_status: "clear",
                citations: [],
                lineage: {
                  base_release: "release:moonshot-ai:kimi:k3",
                  relation: "quantized",
                  root_release: "release:moonshot-ai:kimi:k3",
                  derivative_counts: null,
                },
              },
              {
                release_id: "release:moonshot-ai:kimi:k3",
                name: "Kimi K3",
                lifecycle: "verified",
                lane: "deployable_onprem",
                category: "multimodal",
                first_observed_at: "2026-08-01T09:00:00Z",
                age_hours: 48,
                freshness: "fresh",
                confidence: 0.95,
                review_status: "clear",
                citations: [],
                lineage: {
                  base_release: null,
                  relation: null,
                  root_release: "release:moonshot-ai:kimi:k3",
                  derivative_counts: { quantized: 1 },
                },
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

  // Default view: one row per root, derivative hidden behind the toggle.
  expect(await screen.findByText("Kimi K3")).toBeVisible();
  expect(screen.queryByText("Kimi K3 GGUF")).not.toBeInTheDocument();
  const toggle = screen.getByRole("button", { name: /1 quantized/i });
  expect(toggle).toHaveAttribute("aria-expanded", "false");

  await user.click(toggle);
  expect(screen.getByText("Kimi K3 GGUF")).toBeVisible();
  expect(
    screen.getByRole("button", { name: /1 quantized/i }),
  ).toHaveAttribute("aria-expanded", "true");

  // All-artifacts view flattens the grouping.
  await user.selectOptions(
    screen.getByRole("combobox", { name: "View" }),
    "all",
  );
  expect(screen.getByText("Kimi K3 GGUF")).toBeVisible();
  expect(
    screen.queryByRole("button", { name: /1 quantized/i }),
  ).not.toBeInTheDocument();
});
