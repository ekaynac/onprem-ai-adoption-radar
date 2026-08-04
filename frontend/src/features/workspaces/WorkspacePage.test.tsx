import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { WorkspacePage } from "./WorkspacePage";


test("workspace creation requires no account fields", async () => {
  let workspaces: unknown[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/alerts")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              version: "alerts-v1",
              generated_at: "2026-08-04T10:00:00Z",
              window_days: 14,
              profile_terms: ["vllm"],
              alerts: [],
              counts: { act: 0, evaluate: 0 },
            }),
            { status: 200 },
          ),
        );
      }
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body));
        const created = {
          id: "workspace:ai-lab",
          schema_version: 1,
          devices: [],
          workloads: [],
          policies: {},
          watchlists: [],
          ...body,
        };
        workspaces = [created];
        return Promise.resolve(
          new Response(JSON.stringify(created), { status: 201 }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(workspaces), { status: 200 }),
      );
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <WorkspacePage />
    </QueryClientProvider>,
  );

  expect(screen.queryByLabelText(/email|password|user/i)).not.toBeInTheDocument();
  await user.type(screen.getByLabelText("Profile name"), "AI Lab");
  await user.type(
    screen.getByLabelText("Engines (comma, name@version)"),
    "vllm@0.10, ollama",
  );
  await user.type(
    screen.getByLabelText("Models in production (comma)"),
    "qwen3-32b",
  );
  await user.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByText("AI Lab")).toBeVisible();
  expect(screen.getByText(/3 stack entries/)).toBeVisible();
  vi.unstubAllGlobals();
});


test("static mode renders the demo profile and its alert feed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "1.0",
            generated_at: "2026-08-04T10:00:00Z",
            stack_demo: {
              profile: {
                name: "Mega reference stack (demo)",
                devices: [{ device_id: "rtx-4090-24gb", count: 2 }],
                stack: {
                  engines: [{ name: "vllm", version: "0.10" }],
                  models: ["qwen3-32b"],
                  quant_formats: ["gguf"],
                },
              },
              alerts: {
                version: "alerts-v1",
                generated_at: "2026-08-04T10:00:00Z",
                window_days: 14,
                profile_terms: ["vllm", "qwen3-32b", "gguf"],
                alerts: [
                  {
                    id: "alert:news:news:vllm-break",
                    source: "news",
                    verdict: "act",
                    subject: "vLLM drops V0 engine",
                    what_happened: "V0 removed; migrate.",
                    matched_components: ["vllm"],
                    event_type: "breaking-change",
                    receipts: ["https://blog.vllm.ai/v0-removal"],
                    observed_at: "2026-08-02T09:00:00Z",
                  },
                ],
                counts: { act: 1, evaluate: 0 },
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
      <WorkspacePage staticMode />
    </QueryClientProvider>,
  );

  expect(
    await screen.findByText("Mega reference stack (demo)"),
  ).toBeVisible();
  expect(screen.getByText("vLLM drops V0 engine")).toBeVisible();
  expect(screen.getByText("Act")).toBeVisible();
  expect(screen.getByText(/Matched: vllm/)).toBeVisible();
  // No creation form in the public demo.
  expect(screen.queryByLabelText("Profile name")).not.toBeInTheDocument();
  vi.unstubAllGlobals();
});
