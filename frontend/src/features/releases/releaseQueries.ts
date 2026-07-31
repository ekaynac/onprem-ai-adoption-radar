import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";
import { useActiveWorkspaceId } from "../workspaces/workspaceStore";


export type ReleaseChange = components["schemas"]["ReleaseChange"];
export type CatalogItem = components["schemas"]["CatalogItem"];
export type OperationsHealth = components["schemas"]["OperationsSnapshot"] & {
  fresh_claim_pct?: number;
};

type Page<T> = {
  items: T[];
  next_cursor?: string | null;
};


export { useActiveWorkspaceId };


export function usePriorityReleases(
  workspaceId?: string,
  limit = 50,
) {
  return useQuery({
    queryKey: ["releases", "priority", workspaceId ?? "public", limit],
    queryFn: () => {
      const since = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000);
      const params = new URLSearchParams({
        since: since.toISOString(),
        limit: String(limit),
      });
      if (workspaceId) {
        params.set("workspace_id", workspaceId);
      }
      return apiFetch<Page<ReleaseChange>>(`/api/v1/releases?${params}`);
    },
  });
}


export function useRecommendedActions(workspaceId?: string) {
  return useQuery({
    queryKey: ["catalog", "recommended", workspaceId ?? "public"],
    queryFn: () => {
      const params = new URLSearchParams({
        lifecycle: "recommended",
        limit: "8",
      });
      if (workspaceId) {
        params.set("workspace_id", workspaceId);
      }
      return apiFetch<Page<CatalogItem>>(`/api/v1/catalog?${params}`);
    },
  });
}


export function useCatalogHealth() {
  return useQuery({
    queryKey: ["operations", "health"],
    queryFn: () => apiFetch<OperationsHealth>("/api/v1/operations"),
    refetchInterval: 60_000,
  });
}


export function useReleaseDetail(releaseId: string) {
  return useQuery({
    queryKey: ["release", releaseId],
    queryFn: () =>
      apiFetch<ReleaseChange>(
        `/api/v1/releases/${encodeURIComponent(releaseId)}`,
      ),
    enabled: Boolean(releaseId),
  });
}
