import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { PlannerPage } from "./PlannerPage";


afterEach(() => {
  vi.unstubAllGlobals();
});


function snapshotResponse() {
  return Promise.resolve(
    new Response(
      JSON.stringify({
        schema_version: "1.0",
        generated_at: "2026-08-04T10:00:00Z",
        planner: {
          devices: ["rtx-4090-24gb", "h100-80gb"],
          context_tokens: 4096,
          fits: [
            {
              device: "rtx-4090-24gb",
              model_id: "kimi-k3-mini",
              device_name: "RTX 4090 24GB",
              usable_gb: 21.6,
              verdict: "fits_quantized",
              best_quant_format: "GGUF Q4_K_M",
              best_quant_memory_gb: 6.2,
              context_tokens: 4096,
              note: "",
            },
            {
              device: "h100-80gb",
              model_id: "kimi-k3-mini",
              device_name: "H100 80GB",
              usable_gb: 72,
              verdict: "fits",
              best_quant_format: "FP16",
              best_quant_memory_gb: 17.4,
              context_tokens: 4096,
              note: "",
            },
          ],
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


function renderPlanner(staticMode: boolean) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PlannerPage staticMode={staticMode} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}


test("static planner answers fit questions from the precomputed grid", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => snapshotResponse()),
  );
  const user = userEvent.setup();

  renderPlanner(true);

  await user.selectOptions(
    await screen.findByLabelText("Model"),
    "kimi-k3-mini",
  );
  await user.selectOptions(screen.getByLabelText("Device"), "rtx-4090-24gb");

  expect(screen.getByText("Fits quantized")).toBeVisible();
  expect(screen.getByText("Best fitting quant: GGUF Q4_K_M")).toBeVisible();
  expect(
    screen.getByText("Estimated 6.2 GB of 21.6 GB usable"),
  ).toBeVisible();
  // Static mode: no live workload solver form.
  expect(
    screen.queryByRole("button", { name: /plan workload/i }),
  ).not.toBeInTheDocument();
});


test("live planner requests a workload plan from the capacity API", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/capacity/plan")) {
        expect(init?.method).toBe("POST");
        return Promise.resolve(
          new Response(
            JSON.stringify({
              feasible: true,
              n_gpus: 2,
              recipe: "vllm serve kimi-k3-mini --tensor-parallel-size 2",
              reasons: [],
              assumptions: ["fp16 KV cache"],
            }),
            { status: 200 },
          ),
        );
      }
      return snapshotResponse();
    }),
  );
  const user = userEvent.setup();

  renderPlanner(false);

  await user.selectOptions(
    await screen.findByLabelText("Model"),
    "kimi-k3-mini",
  );
  await user.selectOptions(screen.getByLabelText("Device"), "h100-80gb");
  await user.click(screen.getByRole("button", { name: /plan workload/i }));

  expect(await screen.findByText("Workload plan: 2 GPUs")).toBeVisible();
  expect(screen.getByText("fp16 KV cache")).toBeVisible();
  expect(
    screen.getByText("vllm serve kimi-k3-mini --tensor-parallel-size 2"),
  ).toBeVisible();
});
