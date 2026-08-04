import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";


export type CatalogItem = components["schemas"]["CatalogItem"] & {
  profile?: ModelProfile | null;
};
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
  ring?: string | null;
  score?: number | null;
  architecture?: Record<string, unknown> | null;
  first_tracked_at?: string | null;
  downloads_history?: Array<{
    observed_at: string;
    downloads: number;
  }>;
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
};

export type CatalogFacets = {
  publisher: string[];
  license: string[];
  hardware: string[];
  modality: string[];
  platform: string[];
  freshness: string[];
};

type CatalogPage = {
  items: CatalogItem[];
  next_cursor?: string | null;
};

export type BriefingPick = {
  project: string;
  category?: string | null;
  ring: string;
  backer?: string | null;
  trend?: string | null;
  risk_level?: string | null;
  score?: number | null;
  note?: string | null;
  evidence_notes: string[];
};

export type BriefingMover = {
  subject: string;
  kind: string;
  change_type: string;
  ring?: string | null;
  previous_ring?: string | null;
  observed_at?: string | null;
  line: string;
};

export type Briefing = {
  rings: {
    projects: Record<string, number>;
    models: Record<string, number>;
  };
  try_this_week: BriefingPick[];
  movers: BriefingMover[];
};

export type PlannerFit = {
  device: string;
  model_id: string;
  device_name: string;
  usable_gb: number;
  verdict: string;
  best_quant_format?: string | null;
  best_quant_memory_gb?: number | null;
  context_tokens: number;
  note?: string;
};

export type PlannerGrid = {
  devices: string[];
  context_tokens: number;
  fits: PlannerFit[];
};

export type PublicSnapshot = {
  schema_version: "1.0";
  generated_at: string;
  briefing?: Briefing | null;
  planner?: PlannerGrid | null;
  models?: Array<Record<string, unknown>>;
  project_data?: {
    mode: "live_projection" | "last_published_baseline" | "unavailable";
    generated_at?: string | null;
  };
  projects: PublicProject[];
  model_candidates: ModelCandidate[];
  platforms: PlatformRecord[];
  hardware: HardwareRecord[];
  research: ResearchRecord[];
  latest_digest?: {
    generated_at: string;
    html_url: string;
    card_url?: string;
  } | null;
  source_health: {
    open_review_count: number;
    stale_claim_count: number;
    source_health: SourceHealthRecord[];
  };
  quality?: {
    models?: {
      total: number;
      verified_or_better: number;
      with_license?: number;
      with_parameters?: number;
      with_context?: number;
      with_hardware_tier?: number;
    };
    hardware?: {
      total: number;
      with_spec_url?: number;
      with_bandwidth?: number;
      with_power?: number;
      with_interconnect?: number;
    };
    projects?: {
      total: number;
      with_repository?: number;
      with_evidence?: number;
    };
    research?: {
      total: number;
      with_papers?: number;
      with_implementations?: number;
    };
  };
  source_coverage?: Array<{
    id: string;
    type: string;
    enabled: boolean;
    status: string;
  }>;
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
  status?: "ok" | "empty" | "error" | "stale" | string;
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
      if (filters.lane !== "all") {
        params.set("lane", filters.lane);
      }
      for (const name of [
        "publisher",
        "license",
        "hardware",
        "modality",
        "platform",
        "freshness",
      ] as const) {
        if (filters[name] !== "all") params.set(name, filters[name]);
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


export function useCatalogFacets() {
  return useQuery({
    queryKey: ["catalog", "facets"],
    queryFn: ({ signal }) =>
      apiFetch<CatalogFacets>("/api/v1/catalog/facets", { signal }),
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


export function usePublicSnapshot(enabled = true) {
  return useQuery({
    queryKey: ["public-snapshot"],
    queryFn: ({ signal }) =>
      apiFetch<PublicSnapshot>(
        "/api/v1/integrations/public-snapshot",
        { signal },
      ),
    enabled,
  });
}
