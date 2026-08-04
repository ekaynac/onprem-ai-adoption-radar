import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { DeskPage } from "./DeskPage";


afterEach(() => {
  vi.unstubAllGlobals();
});


test("renders the brief with verdict pills, receipts, and the ledger", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "1.0",
            generated_at: "2026-08-04T10:00:00Z",
            desk: {
              brief: {
                id: "brief-2026-W32",
                generated_at: "2026-08-04T10:00:00Z",
                window_days: 7,
                verdict_rules: "Deterministic v1 rules",
                verdict_counts: { act: 1, evaluate: 1, ignore: 0 },
                spotlight: {
                  task: "coding",
                  task_label: "Coding assistant",
                  device: "rtx-4090-24gb",
                  top_candidate: {
                    model_id: "mistral-small-3",
                    name: "Mistral Small 3",
                    ring: "adopt",
                    fit_verdict: "fits",
                    reasons: ["Fit: fits on RTX 4090 24GB"],
                  },
                  note: "",
                },
                items: [
                  {
                    id: "call:brief-2026-W32:ring-moves:qwen3-32b",
                    section: "ring-moves",
                    subject: "qwen3-32b",
                    what_happened: "Model ring pilot → adopt (promoted)",
                    why_it_matters: "Deployment advice changed",
                    verdict: "act",
                    rationale: "Promotion into adopt",
                    receipts: ["data/model-history.jsonl"],
                    observed_at: "2026-08-02T08:00:00Z",
                  },
                  {
                    id: "call:brief-2026-W32:benchmark-moves:x",
                    section: "benchmark-moves",
                    subject: "qwen3-32b · mmlu-pro",
                    what_happened: "mmlu-pro moved +5 points",
                    why_it_matters: "Capability ranking changed",
                    verdict: "evaluate",
                    rationale: "Re-rank candidates",
                    receipts: ["https://ollb.example"],
                    observed_at: "2026-08-03T08:00:00Z",
                  },
                ],
              },
              calls: [
                {
                  call_id: "call:brief-2026-W31:ring-moves:vllm",
                  brief_id: "brief-2026-W31",
                  subject: "vllm",
                  verdict: "act",
                  rationale: "Promotion",
                  made_at: "2026-07-27T10:00:00Z",
                  status: "confirmed",
                  resolved_at: "2026-08-03T10:00:00Z",
                  note: "Pilot succeeded",
                },
              ],
              track_record: {
                total: 3,
                open: 2,
                confirmed: 1,
                wrong: 0,
                expired: 0,
                hit_rate_pct: 100,
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

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DeskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText(/brief-2026-W32/)).toBeVisible();
  expect(screen.getByLabelText("Track record")).toHaveTextContent("100% hit rate");
  expect(screen.getAllByText("Act").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("Model ring pilot → adopt (promoted)")).toBeVisible();
  expect(screen.getByRole("link", { name: "receipt ↗" })).toHaveAttribute(
    "href",
    "https://ollb.example",
  );
  const spotlight = screen.getByRole("link", { name: "Mistral Small 3" });
  expect(spotlight).toHaveAttribute(
    "href",
    "/advisor?task=coding&device=rtx-4090-24gb",
  );
  expect(screen.getByText("Pilot succeeded")).toBeVisible();
});
