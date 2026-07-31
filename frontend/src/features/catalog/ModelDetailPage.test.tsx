import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { ModelDetailPage } from "./ModelDetailPage";


test("unknown claim is explicit and cited values link to evidence", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            release: {
              release_id: "release:kimi-k3",
              name: "Kimi K3",
              category: "text_reasoning",
              lane: "deployable_onprem",
              lifecycle: "verified",
              first_observed_at: "2026-07-30T10:00:00Z",
              public_recommendation: {
                release_id: "release:kimi-k3",
                workspace_id: null,
                ring: null,
                public_ring: null,
                reasons: [],
                assumptions: [],
                evidence_ids: [],
                changed_factors: [],
                computation_version: "test",
              },
              matched_terms: [],
            },
            claims: [
              {
                predicate: "context_length",
                state: "unknown",
                reason: "No official value found",
                citations: [],
              },
              {
                predicate: "license",
                state: "verified",
                value: "kimi-k3",
                citations: [
                  {
                    evidence_id: "evidence:official",
                    url: "https://moonshot.ai/kimi-k3",
                    label: "Official source",
                    strength: "official_documentation",
                  },
                ],
              },
            ],
            compatibility: [],
            qualification: null,
            profile: {
              id: "kimi-k3",
              family: "Kimi",
              warnings: ["Curated seed baseline; scan enrichment is pending"],
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
      <MemoryRouter initialEntries={["/catalog/release:kimi-k3"]}>
        <Routes>
          <Route path="/catalog/:releaseId" element={<ModelDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect((await screen.findAllByText("Unknown"))[0]).toBeVisible();
  expect(screen.getByText("No official value found")).toBeVisible();
  expect(screen.getByRole("link", { name: /official source/i })).toHaveAttribute(
    "href",
    "https://moonshot.ai/kimi-k3",
  );
  expect(
    screen.getByText("Curated seed baseline; scan enrichment is pending"),
  ).toBeVisible();
  vi.unstubAllGlobals();
});
