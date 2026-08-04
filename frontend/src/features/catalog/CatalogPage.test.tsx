import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

import { CatalogPage } from "./CatalogPage";


test("filters all six model categories", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(
          JSON.stringify({ items: [], next_cursor: null }),
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
        <CatalogPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const category = screen.getByLabelText("Model category");
  for (const name of [
    "Text & reasoning",
    "Multimodal",
    "Embedding & reranking",
    "Speech & audio",
    "Image & video",
    "Vision & documents",
  ]) {
    expect(within(category).getByRole("option", { name })).toBeVisible();
  }
  vi.unstubAllGlobals();
});


test("sends the selected lane to catalog search", async () => {
  const fetchMock = vi.fn(() =>
    Promise.resolve(
      new Response(JSON.stringify({ items: [], next_cursor: null }), {
        status: 200,
      }),
    ),
  );
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CatalogPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await user.selectOptions(screen.getByLabelText("Lane"), "market_reference");

  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("lane=market_reference"),
      expect.anything(),
    );
  });
  vi.unstubAllGlobals();
});


test("populates metadata facets and sends selected license", async () => {
  const fetchMock = vi.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const payload = url.includes("/catalog/facets")
      ? {
          publisher: ["publisher:moonshot-ai"],
          license: ["modified-mit"],
          hardware: ["datacenter"],
          modality: ["image-text-to-text"],
          platform: ["transformers"],
          freshness: ["fresh", "stale"],
        }
      : { items: [], next_cursor: null };
    return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const user = userEvent.setup();

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter><CatalogPage /></MemoryRouter>
    </QueryClientProvider>,
  );

  await user.selectOptions(await screen.findByLabelText("License"), "modified-mit");
  await waitFor(() => {
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("license=modified-mit"),
      expect.anything(),
    );
  });
  expect(screen.queryByLabelText("Review status")).not.toBeInTheDocument();
  vi.unstubAllGlobals();
});


test("base-model view hides derivatives; all-artifacts view shows them", async () => {
  const items = [
    {
      release_id: "release:legacy:kimi-k3",
      name: "Kimi K3",
      category: "multimodal",
      lane: "deployable_onprem",
      lifecycle: "verified",
      first_observed_at: "2026-08-01T09:00:00Z",
      matched_terms: [],
      public_recommendation: {
        release_id: "release:legacy:kimi-k3",
        workspace_id: null,
        ring: "adopt",
        public_ring: "adopt",
        reasons: [],
        assumptions: [],
        evidence_ids: [],
        changed_factors: [],
        computation_version: "legacy-ring-bridge-v1",
      },
      workspace_recommendation: null,
      lineage: {
        base_release: null,
        relation: null,
        root_release: "release:legacy:kimi-k3",
        derivative_counts: { quantized: 1 },
      },
      profile: {
        family: "Kimi",
        params_total: 1_000_000_000_000,
        params_active: 32_000_000_000,
        context_length: 262144,
        license: "modified-mit",
        hardware_tier: "datacenter",
      },
    },
    {
      release_id: "release:grearl:kimi-k3-gguf",
      name: "Kimi K3 GGUF",
      category: "multimodal",
      lane: "deployable_onprem",
      lifecycle: "detected",
      first_observed_at: "2026-08-02T09:00:00Z",
      matched_terms: [],
      public_recommendation: {
        release_id: "release:grearl:kimi-k3-gguf",
        workspace_id: null,
        ring: null,
        public_ring: null,
        reasons: [],
        assumptions: [],
        evidence_ids: [],
        changed_factors: [],
        computation_version: "public-snapshot-v1",
      },
      workspace_recommendation: null,
      lineage: {
        base_release: "release:legacy:kimi-k3",
        relation: "quantized",
        root_release: "release:legacy:kimi-k3",
        derivative_counts: null,
      },
      profile: null,
    },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ items, next_cursor: null }), {
          status: 200,
        }),
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
        <CatalogPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );

  // Default (base models): root visible with its classic columns; the
  // quantization is collapsed out.
  expect(await screen.findByText("Kimi K3")).toBeVisible();
  expect(screen.queryByText("Kimi K3 GGUF")).not.toBeInTheDocument();
  expect(screen.getByText("1T A32B")).toBeVisible();
  expect(screen.getByText("256K")).toBeVisible();
  expect(screen.getByText("modified-mit")).toBeVisible();
  expect(screen.getByText("adopt")).toBeVisible();
  expect(screen.getByText("1 quantized")).toBeVisible();

  await user.selectOptions(screen.getByLabelText("View"), "all");
  expect(screen.getByText("Kimi K3 GGUF")).toBeVisible();
  expect(screen.getByText(/quantized of/)).toBeVisible();
  vi.unstubAllGlobals();
});
