import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { SourceHealthPage } from "./SourceHealthPage";


test("shows data-quality coverage and disabled source families", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.includes("public-snapshot")
      ? {
          quality: {
            models: { total: 20, verified_or_better: 12, with_license: 15 },
            hardware: { total: 8, with_spec_url: 6 },
            projects: { total: 10, with_repository: 9 },
            research: { total: 7, with_implementations: 4 },
          },
          source_coverage: [
            { id: "huggingface", type: "huggingface", enabled: true, status: "active" },
            { id: "external-model-registries", type: "json_registries", enabled: false, status: "disabled_pending_contract_verification" },
          ],
        }
      : { source_health: [], open_review_count: 0, stale_claim_count: 0 };
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><SourceHealthPage staticMode /></MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("12/20")).toBeVisible();
  expect(screen.getByText("verified models")).toBeVisible();
  expect(screen.getByText("external-model-registries")).toBeVisible();
  expect(screen.getByText("Contract verification pending")).toBeVisible();
  expect(screen.queryByRole("link", { name: /Review queue/ })).toBeNull();
  vi.unstubAllGlobals();
});
