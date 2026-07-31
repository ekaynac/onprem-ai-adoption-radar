import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { HardwarePage } from "./HardwarePage";
import { PlatformDetailPage } from "./PlatformDetailPage";
import { ProjectsPage } from "./ProjectsPage";
import { ResearchPage } from "./ResearchPage";


const snapshot = {
  schema_version: "1.0",
  generated_at: "2026-07-31T08:00:00Z",
  projects: [
    {
      project: "vLLM",
      category: "model_serving",
      ring: "adopt",
      score: 4.7,
      summary: "High-throughput serving engine.",
      workflow_fit: { serving: "strong" },
      risk_level: "medium",
      what_changed: ["Released a new scheduler."],
      why_it_matters: "Improves GPU utilization.",
      on_prem_fit: "Strong cluster fit.",
      risk_reasons: [],
      risks: [],
      try_this_week: ["Benchmark throughput."],
      try_next: [],
      evidence: ["https://github.com/vllm-project/vllm"],
      evidence_notes: [],
      trend: "rising",
      tags: [],
      last_reviewed_at: "2026-07-31T08:00:00Z",
      repository_url: "https://github.com/vllm-project/vllm",
      sources: [],
      history: [],
      latest_metrics: { stars: 68000 },
    },
  ],
  model_candidates: [],
  platforms: [
    {
      id: "vllm",
      name: "vLLM",
      repo_url: "https://github.com/vllm-project/vllm",
      verified_at: "2026-07-30",
      hardware: { nvidia: "yes", amd: "partial" },
      features: { tensor_parallel: "yes", fp8: "yes" },
      sources: ["https://docs.vllm.ai/"],
      notes: "Production serving platform.",
    },
    {
      id: "platform:library:transformers",
      name: "Transformers",
      repo_url: "https://huggingface.co/docs/transformers",
      verified_at: "2026-07-31",
    },
  ],
  hardware: [
    {
      id: "h200",
      name: "NVIDIA H200",
      kind: "gpu",
      gpu_count: 1,
      total_memory_gb: 141,
      memory_bandwidth_gbs: 4800,
      tdp_watts: 700,
      spec_url: "https://nvidia.com/h200",
      datacenter: true,
    },
  ],
  research: [
    {
      id: "paged-attention",
      name: "PagedAttention",
      category: "model_serving",
      domain: "inference",
      aliases: [],
      onprem_impact: "reduces_memory",
      notes: "Makes KV-cache allocation efficient.",
      open_code: true,
      peer_reviewed: true,
      citation_count: 1200,
      score: 4.8,
      ring: "adopt",
      momentum_direction: "rising",
      papers: [
        {
          arxiv_id: "2309.06180",
          title: "Efficient Memory Management for Large Language Model Serving",
          role: "canonical",
          published: "2023-09",
        },
      ],
      resolved_implementations: [],
      warnings: ["Curated seed baseline; scan enrichment is pending"],
    },
  ],
  source_health: {
    open_review_count: 0,
    stale_claim_count: 0,
    source_health: [],
  },
};


afterEach(() => {
  vi.unstubAllGlobals();
});


function renderPage(node: React.ReactNode, route = "/") {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify(snapshot), { status: 200 }),
      ),
    ),
  );
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}


test("restores GitHub projects as navigable intelligence cards", async () => {
  renderPage(<ProjectsPage />);

  expect(await screen.findByRole("heading", { name: "vLLM" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Open intelligence" })).toHaveAttribute(
    "href",
    "/projects/vLLM",
  );
  expect(screen.getByRole("link", { name: "GitHub ↗" })).toHaveAttribute(
    "href",
    "https://github.com/vllm-project/vllm",
  );
});


test("renders hardware specifications instead of JSON records", async () => {
  renderPage(<HardwarePage />);

  expect(await screen.findByRole("heading", { name: "NVIDIA H200" })).toBeVisible();
  expect(screen.getByText("141 GB")).toBeVisible();
  expect(screen.queryByText(/"gpu_count"/)).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open NVIDIA H200 capacity record" })).toHaveAttribute(
    "href",
    "/hardware/h200",
  );
});


test("makes research cards and primary papers clickable", async () => {
  renderPage(<ResearchPage />);

  expect(await screen.findByRole("heading", { name: "PagedAttention" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Open research" })).toHaveAttribute(
    "href",
    "/research/paged-attention",
  );
  expect(screen.getByRole("link", { name: "Paper ↗" })).toHaveAttribute(
    "href",
    "https://arxiv.org/abs/2309.06180",
  );
  expect(
    screen.getByText("Curated seed baseline; scan enrichment is pending"),
  ).toBeVisible();
  expect(screen.queryByText(/"papers"/)).not.toBeInTheDocument();
});


test("renders platform support and evidence instead of JSON", async () => {
  renderPage(
    <Routes>
      <Route path="/platforms/:platformId" element={<PlatformDetailPage />} />
    </Routes>,
    "/platforms/vllm",
  );

  expect(await screen.findByRole("heading", { name: "vLLM", level: 1 })).toBeVisible();
  expect(screen.getByText("tensor parallel")).toBeVisible();
  expect(screen.getByRole("link", { name: "Open repository ↗" })).toHaveAttribute(
    "href",
    "https://github.com/vllm-project/vllm",
  );
  expect(screen.queryByText(/"features"/)).not.toBeInTheDocument();
});


test("renders dynamically discovered platform records with a sparse matrix", async () => {
  renderPage(
    <Routes>
      <Route path="/platforms/:platformId" element={<PlatformDetailPage />} />
    </Routes>,
    "/platforms/platform%3Alibrary%3Atransformers",
  );

  expect(
    await screen.findByRole("heading", { name: "Transformers", level: 1 }),
  ).toBeVisible();
  expect(screen.getByRole("link", { name: "Open repository ↗" })).toHaveAttribute(
    "href",
    "https://huggingface.co/docs/transformers",
  );
});
