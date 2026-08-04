import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { HomePage } from "./HomePage";


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
            advisor: {
              tasks: { coding: { label: "Coding assistant" } },
              devices: ["rtx-4090-24gb", "a100-80gb"],
              answers: {},
            },
            desk: {
              brief: {
                id: "brief-2026-W32",
                generated_at: "2026-08-04T10:00:00Z",
                window_days: 7,
                verdict_rules: "rules",
                verdict_counts: { act: 1, evaluate: 0, ignore: 1 },
                spotlight: null,
                items: [
                  {
                    id: "call:1",
                    section: "ring-moves",
                    subject: "qwen3-32b",
                    what_happened: "Ring pilot → adopt",
                    why_it_matters: "x",
                    verdict: "act",
                    rationale: "r",
                    receipts: [],
                    observed_at: null,
                  },
                  {
                    id: "call:2",
                    section: "new-repos",
                    subject: "acme/slow",
                    what_happened: "slow repo",
                    why_it_matters: "x",
                    verdict: "ignore",
                    rationale: "r",
                    receipts: [],
                    observed_at: null,
                  },
                ],
              },
              calls: [],
              track_record: {
                total: 3,
                open: 2,
                confirmed: 1,
                wrong: 0,
                expired: 0,
                hit_rate_pct: 100,
              },
            },
            stack_demo: {
              profile: {
                name: "Mega reference stack (demo)",
                devices: [],
                stack: { engines: [], models: [], quant_formats: [] },
              },
              alerts: {
                version: "alerts-v1",
                generated_at: "2026-08-04T10:00:00Z",
                window_days: 14,
                profile_terms: [],
                alerts: [],
                counts: { act: 1, evaluate: 2 },
              },
            },
            newsroom: {
              items: [],
              counts: {
                total: 5,
                classified: 3,
                unclassified: 2,
                breaking: 1,
                improvement: 1,
                informational: 1,
              },
              event_types: [],
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


test("question-first home routes to a recommendation in two interactions", async () => {
  stubSnapshot();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/advisor" element={<div>advisor-page</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(
    await screen.findByRole("heading", { name: "What should you run?" }),
  ).toBeVisible();
  // The Desk digest hides ignore-verdict items and shows the score.
  expect(screen.getByText("qwen3-32b")).toBeVisible();
  expect(screen.queryByText("acme/slow")).not.toBeInTheDocument();
  expect(screen.getByLabelText("Public track record")).toHaveTextContent(
    "100% hit rate",
  );
  expect(screen.getByText(/1 act and 2 evaluate/)).toBeVisible();
  expect(screen.getByText(/3 classified item/)).toBeVisible();

  // Interaction 1: pick hardware; interaction 2: ask.
  const button = screen.getByRole("button", { name: "Get the answer" });
  expect(button).toBeDisabled();
  fireEvent.change(screen.getByLabelText("Hardware"), {
    target: { value: "rtx-4090-24gb" },
  });
  fireEvent.click(button);
  expect(await screen.findByText("advisor-page")).toBeVisible();
});
