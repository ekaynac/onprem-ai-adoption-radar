import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";


export type CatalogItem = components["schemas"]["CatalogItem"];
export type CatalogDetail = components["schemas"]["CatalogDetail"];

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
  platforms: Array<Record<string, unknown>>;
  hardware: Array<Record<string, unknown>>;
  research: Array<Record<string, unknown>>;
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
