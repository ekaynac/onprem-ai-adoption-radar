import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";


export type CatalogItem = components["schemas"]["CatalogItem"];
export type ModelProfile = {
  id?: string;
  family?: string;
  hf_repo?: string | null;
  ollama_name?: string | null;
  params_total?: number | null;
  params_active?: number | null;
  context_length?: number | null;
  modality?: string | null;
  license?: string | null;
  openness?: string | null;
  hf_downloads?: number | null;
  hf_likes?: number | null;
  release_date?: string | null;
  last_modified?: string | null;
  use_case?: string | null;
  hardware_tier?: string | null;
  quants?: Array<Record<string, unknown>>;
  benchmarks?: Array<{
    name: string;
    score: number;
    source_url: string;
  }>;
  warnings?: string[];
};

export type CatalogDetail = components["schemas"]["CatalogDetail"] & {
  profile?: ModelProfile | null;
  source_url?: string | null;
  source_strength?: string | null;
};

export type CatalogSearch = {
  query: string;
  category: string;
  lifecycle: string;
  lane: string;
  publisher: string;
  license: string;
  hardware: string;
  modality: string;
  platform: string;
  freshness: string;
  review: string;
};

type CatalogPage = {
  items: CatalogItem[];
  next_cursor?: string | null;
};

export type PublicSnapshot = {
  schema_version: "1.0";
  generated_at: string;
  projects: PublicProject[];
  model_candidates: ModelCandidate[];
  platforms: PlatformRecord[];
  hardware: HardwareRecord[];
  research: ResearchRecord[];
  source_health: {
    open_review_count: number;
    stale_claim_count: number;
    source_health: SourceHealthRecord[];
  };
};

export type PublicProject = {
  project: string;
  category: string;
  ring: string;
  score: number;
  summary: string;
  workflow_fit: Record<string, string>;
  risk_level: string;
  what_changed: string[];
  why_it_matters: string;
  on_prem_fit: string;
  risk_reasons: string[];
  risks: string[];
  try_this_week: string[];
  try_next: string[];
  evidence: string[];
  evidence_notes: string[];
  trend: string;
  tags: string[];
  last_reviewed_at: string;
  repository_url?: string | null;
  sources: Array<{ id: string; type: string; url: string }>;
  history: Array<Record<string, unknown>>;
  latest_metrics?: Record<string, unknown> | null;
  backer?: { name: string; type: string } | null;
};

export type ModelCandidate = {
  hf_repo: string;
  name: string;
  family: string;
  downloads: number;
  likes: number;
  pipeline_tag?: string | null;
  first_observed_at: string;
  last_observed_at: string;
  source_url: string;
  source_strength: string;
};

export type PlatformRecord = {
  id: string;
  name: string;
  repo_url: string;
  verified_at?: string;
  verified?: string;
  checked_at?: string;
  verification_status?: string;
  hardware?: Record<string, string>;
  features?: Record<string, string>;
  sources?: string[];
  notes?: string;
};

export type HardwareRecord = {
  id: string;
  name: string;
  kind: string;
  gpu_count: number;
  total_memory_gb: number;
  aggregate_memory_gb?: number;
  memory_bandwidth_gbs?: number | null;
  tdp_watts?: number | null;
  tflops_fp16?: number | null;
  tflops_fp8?: number | null;
  tflops_fp4?: number | null;
  interconnect?: string | null;
  spec_url?: string | null;
  verified?: string | null;
  datacenter?: boolean;
};

export type ResearchRecord = {
  id: string;
  name: string;
  category: string;
  domain: string;
  aliases: string[];
  onprem_impact: string;
  notes?: string | null;
  open_code: boolean;
  peer_reviewed?: boolean | null;
  citation_count?: number | null;
  citation_source?: string | null;
  score?: number | null;
  ring?: string | null;
  momentum_direction?: string | null;
  momentum_note?: string | null;
  papers: Array<{
    arxiv_id: string;
    title: string;
    role: string;
    published?: string | null;
  }>;
  resolved_implementations: Array<{
    kind: string;
    ref: string;
    ring?: string | null;
    note?: string | null;
  }>;
  score_breakdown?: Record<string, number> | null;
  warnings: string[];
};

export type SourceHealthRecord = {
  source_id: string;
  last_success_at?: string | null;
  consecutive_failures: number;
  latency_ms?: number | null;
  items_count?: number | null;
  circuit_open_until?: string | null;
};

export function useCatalogSearch(
  filters: CatalogSearch,
  workspaceId?: string,
) {
  return useQuery({
    queryKey: ["catalog", filters, workspaceId ?? "public"],
    queryFn: ({ signal }) => {
      const params = new URLSearchParams({
        q: filters.query,
        limit: "100",
      });
      if (filters.category !== "all") {
        params.set("category", filters.category);
      }
      if (filters.lifecycle !== "all") {
        params.set("lifecycle", filters.lifecycle);
      }
      if (workspaceId) {
        params.set("workspace_id", workspaceId);
      }
      return apiFetch<CatalogPage>(
        `/api/v1/catalog?${params}`,
        { signal },
      );
    },
  });
}


export function useCatalogDetail(
  releaseId: string,
  workspaceId?: string,
) {
  return useQuery({
    queryKey: ["catalog-detail", releaseId, workspaceId ?? "public"],
    queryFn: ({ signal }) => {
      const suffix = workspaceId
        ? `?workspace_id=${encodeURIComponent(workspaceId)}`
        : "";
      return apiFetch<CatalogDetail>(
        `/api/v1/catalog/${encodeURIComponent(releaseId)}${suffix}`,
        { signal },
      );
    },
    enabled: Boolean(releaseId),
  });
}


export function usePublicSnapshot() {
  return useQuery({
    queryKey: ["public-snapshot"],
    queryFn: ({ signal }) =>
      apiFetch<PublicSnapshot>(
        "/api/v1/integrations/public-snapshot",
        { signal },
      ),
  });
}
