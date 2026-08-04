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


test("shows tenure, download sparkline, lineage, and tracked variants", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("public-snapshot")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              schema_version: "1.0",
              generated_at: "2026-08-04T09:00:00Z",
              models: [
                {
                  release_id: "release:legacy:kimi-k3",
                  name: "Kimi K3",
                  lineage: {
                    root_release: "release:legacy:kimi-k3",
                    relation: null,
                  },
                },
                {
                  release_id: "release:grearl:kimi-k3-gguf",
                  name: "Kimi K3 GGUF",
                  lineage: {
                    root_release: "release:legacy:kimi-k3",
                    relation: "quantized",
                  },
                },
              ],
              projects: [],
              model_candidates: [],
              platforms: [],
              hardware: [],
              research: [],
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
      return Promise.resolve(
        new Response(
          JSON.stringify({
            release: {
              release_id: "release:legacy:kimi-k3",
              name: "Kimi K3",
              category: "multimodal",
              lane: "deployable_onprem",
              lifecycle: "verified",
              first_observed_at: "2026-07-01T10:00:00Z",
              public_recommendation: {
                release_id: "release:legacy:kimi-k3",
                workspace_id: null,
                ring: "adopt",
                public_ring: "adopt",
                reasons: ["Deterministic curated score 4.2/5"],
                assumptions: [],
                evidence_ids: [],
                changed_factors: [],
                computation_version: "legacy-ring-bridge-v1",
              },
              matched_terms: [],
              lineage: {
                base_release: null,
                relation: null,
                root_release: "release:legacy:kimi-k3",
                derivative_counts: { quantized: 1 },
              },
            },
            claims: [],
            compatibility: [],
            qualification: null,
            profile: {
              id: "kimi-k3",
              family: "Kimi",
              first_tracked_at: "2026-07-01T08:00:00Z",
              downloads_history: [
                { observed_at: "2026-07-01T08:00:00Z", downloads: 1000 },
                { observed_at: "2026-07-02T08:00:00Z", downloads: 1500 },
                { observed_at: "2026-07-03T08:00:00Z", downloads: 2400 },
              ],
            },
          }),
          { status: 200 },
        ),
      );
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/catalog/release:legacy:kimi-k3"]}>
        <Routes>
          <Route path="/catalog/:releaseId" element={<ModelDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("adopt")).toBeVisible();
  expect(screen.getByText("Deterministic curated score 4.2/5")).toBeVisible();
  expect(screen.getByText(/Tracked for \d+ days \(since/)).toBeVisible();
  expect(
    screen.getByRole("img", { name: /Downloads over the last 3 scans/ }),
  ).toBeVisible();
  expect(
    screen.getByText("Base release — no declared upstream model."),
  ).toBeVisible();
  expect(await screen.findByText("1 tracked variant")).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Kimi K3 GGUF" }),
  ).toHaveAttribute("href", "/catalog/release%3Agrearl%3Akimi-k3-gguf");
});


test("triangulated benchmark table groups sources with badges and percentile", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("public-snapshot")) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              schema_version: "1.0",
              generated_at: "2026-08-04T09:00:00Z",
              models: [],
              projects: [],
              model_candidates: [],
              platforms: [],
              hardware: [],
              research: [],
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
      return Promise.resolve(
        new Response(
          JSON.stringify({
            release: {
              release_id: "release:legacy:deepseek-r1",
              name: "DeepSeek R1",
              category: "text_reasoning",
              lane: "deployable_onprem",
              lifecycle: "verified",
              first_observed_at: "2026-07-01T10:00:00Z",
              public_recommendation: {
                release_id: "release:legacy:deepseek-r1",
                workspace_id: null,
                ring: "adopt",
                public_ring: "adopt",
                reasons: [],
                assumptions: [],
                evidence_ids: [],
                changed_factors: [],
                computation_version: "legacy-ring-bridge-v1",
              },
              matched_terms: [],
            },
            claims: [],
            compatibility: [],
            qualification: null,
            profile: {
              id: "deepseek-r1",
              family: "DeepSeek",
              benchmark_aggregates: [
                {
                  benchmark: "mmlu-pro",
                  label: "MMLU-Pro",
                  consensus: 75,
                  spread: 9,
                  self_reported_gap: 9,
                  flagged: true,
                  percentile: 100,
                  sample_size: 2,
                  scores: [
                    {
                      source_id: "open-llm-leaderboard",
                      score: 75,
                      source_url: "https://ollb.example/r1",
                      self_reported: false,
                    },
                    {
                      source_id: "model-card",
                      score: 84,
                      source_url: "https://card.example/r1",
                      self_reported: true,
                    },
                  ],
                },
              ],
            },
          }),
          { status: 200 },
        ),
      );
    }),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/catalog/release:legacy:deepseek-r1"]}>
        <Routes>
          <Route path="/catalog/:releaseId" element={<ModelDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  expect(await screen.findByText("Benchmarks — triangulated")).toBeVisible();
  expect(
    screen.getByRole("link", { name: "open-llm-leaderboard" }),
  ).toHaveAttribute("href", "https://ollb.example/r1");
  expect(screen.getByText("self-reported")).toBeVisible();
  expect(screen.getByText("p100 of 2 tracked")).toBeVisible();
  expect(screen.getByTitle(/differs from independent by 9 points/)).toBeVisible();
});
