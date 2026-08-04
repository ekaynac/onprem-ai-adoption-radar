import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { AdvisorPage } from "./AdvisorPage";


afterEach(() => {
  vi.unstubAllGlobals();
});


const ANSWER = {
  version: "advisor-v1",
  task: "coding",
  task_label: "Coding assistant",
  device: "RTX 4090 24GB",
  context_tokens: 4096,
  cost: {
    board_power_kw: 0.45,
    indicative_hardware_usd: 1900,
    note: "Device-level board power and indicative list price; workload-specific $/Mtok comes from the planner",
  },
  candidates: [
    {
      model_id: "qwen3-8b",
      name: "Qwen3-8B",
      release_id: "release:legacy:qwen3-8b",
      ring: "adopt",
      composite: 0.85,
      fit: {
        verdict: "fits",
        best_quant_format: "GGUF Q4_K_M",
        best_quant_memory_gb: 8.4,
        usable_gb: 20.4,
        context_tokens: 4096,
      },
      task_capability: {
        percentile: 60,
        benchmarks: [
          {
            benchmark: "aider-polyglot",
            label: "Aider polyglot (pass rate)",
            consensus: 45,
            percentile: 60,
            sample_size: 5,
            flagged: false,
          },
        ],
      },
      license: { value: "apache-2.0", allowed: true },
      params_total: 8_000_000_000,
      params_active: null,
      context_length: 131072,
      maturity_score: 4.0,
      reasons: ["Fit: fits on RTX 4090 24GB", "Curated ring: adopt"],
      assumptions: [],
    },
    {
      model_id: "phi-4",
      name: "Phi-4",
      release_id: "release:legacy:phi-4",
      ring: "pilot",
      composite: 0.7,
      fit: {
        verdict: "fits",
        best_quant_format: "GGUF Q4_K_M",
        best_quant_memory_gb: 9.1,
        usable_gb: 20.4,
        context_tokens: 4096,
      },
      task_capability: null,
      license: { value: "mit", allowed: true },
      params_total: 14_000_000_000,
      params_active: null,
      context_length: 16384,
      maturity_score: 3.5,
      reasons: ["Fit: fits on RTX 4090 24GB"],
      assumptions: [
        "No tracked benchmarks for this task — ranked on the curated composite score instead",
      ],
    },
  ],
  excluded: [{ model_id: "huge", reason: "Won't fit on RTX 4090 24GB" }],
  assumptions: [],
};

function snapshotResponse() {
  return Promise.resolve(
    new Response(
      JSON.stringify({
        schema_version: "1.0",
        generated_at: "2026-08-04T10:00:00Z",
        advisor: {
          tasks: { coding: { label: "Coding assistant" } },
          devices: ["rtx-4090-24gb"],
          answers: { "coding|rtx-4090-24gb": ANSWER },
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
  );
}


function renderAdvisor(staticMode: boolean, initialEntry = "/advisor") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <AdvisorPage staticMode={staticMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}


test("static advisor answers from the precomputed grid with visible exclusions", async () => {
  vi.stubGlobal("fetch", vi.fn(() => snapshotResponse()));
  const user = userEvent.setup();

  renderAdvisor(true);

  await user.selectOptions(
    await screen.findByLabelText("Hardware"),
    "rtx-4090-24gb",
  );

  expect(screen.getByText("1. Qwen3-8B")).toBeVisible();
  expect(screen.getByText(/Task capability p60/)).toBeVisible();
  expect(screen.getByText(/~0.45 kW board power/)).toBeVisible();
  expect(
    screen.getByText(/Assumption: No tracked benchmarks/),
  ).toBeVisible();

  // Policy gate applies client-side over the precomputed answer, visibly.
  await user.selectOptions(screen.getByLabelText("License policy"), "mit");
  expect(screen.queryByText("1. Qwen3-8B")).not.toBeInTheDocument();
  await user.click(screen.getByText(/excluded — every exclusion has a reason/));
  expect(
    screen.getByText(/qwen3-8b: License apache-2.0 does not match policy mit/),
  ).toBeVisible();
  expect(screen.getByText(/huge: Won't fit/)).toBeVisible();
});


test("live advisor recomputes through the recommend API", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/recommend")) {
        expect(init?.method).toBe("POST");
        const body = JSON.parse(String(init?.body));
        expect(body.allowed_licenses).toEqual(["mit"]);
        return Promise.resolve(
          new Response(
            JSON.stringify({
              ...ANSWER,
              candidates: [ANSWER.candidates[1]],
              excluded: [
                {
                  model_id: "qwen3-8b",
                  reason: "License apache-2.0 not in policy ['mit']",
                },
              ],
            }),
            { status: 200 },
          ),
        );
      }
      return snapshotResponse();
    }),
  );
  const user = userEvent.setup();

  renderAdvisor(false, "/advisor?device=rtx-4090-24gb");

  expect(await screen.findByText("1. Qwen3-8B")).toBeVisible();
  await user.selectOptions(screen.getByLabelText("License policy"), "mit");
  await user.click(screen.getByRole("button", { name: "Recompute live" }));

  expect(await screen.findByText("1. Phi-4")).toBeVisible();
  expect(screen.queryByText("1. Qwen3-8B")).not.toBeInTheDocument();
});
