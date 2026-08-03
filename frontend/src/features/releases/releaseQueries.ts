import { useQuery } from "@tanstack/react-query";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";
import type { SourceHealthRecord } from "../catalog/catalogQueries";
import { useActiveWorkspaceId } from "../workspaces/workspaceStore";


export type ReleaseChange = components["schemas"]["ReleaseChange"] & {
  released_at?: string | null;
};
export type CatalogItem = components["schemas"]["CatalogItem"];
export type OperationsHealth = Omit<
  components["schemas"]["OperationsSnapshot"],
  "source_health"
> & {
  fresh_claim_pct?: number;
  source_health: SourceHealthRecord[];
};

type Page<T> = {
  items: T[];
  next_cursor?: string | null;
};


export { useActiveWorkspaceId };


export function releaseAgeHours(item: ReleaseChange, now = Date.now()) {
  const timestamp = Date.parse(item.released_at ?? item.first_observed_at);
  if (Number.isNaN(timestamp)) return Number.POSITIVE_INFINITY;
  return Math.max(0, (now - timestamp) / (60 * 60 * 1000));
}


export type ReleaseLineage = {
  base_release?: string | null;
  relation?: string | null;
  root_release?: string | null;
  derivative_counts?: Record<string, number> | null;
};

export function releaseLineage(
  item: Pick<ReleaseChange, "lineage">,
): ReleaseLineage | null {
  return (item.lineage as ReleaseLineage | null | undefined) ?? null;
}

export function releaseGroupKey(item: ReleaseChange): string {
  return releaseLineage(item)?.root_release ?? item.release_id;
}

export function derivativeCountsLabel(
  counts: Record<string, number> | null | undefined,
  fallbackCount = 0,
): string | null {
  const entries = Object.entries(counts ?? {}).filter(
    ([, count]) => count > 0,
  );
  if (!entries.length) {
    return fallbackCount > 0
      ? `${fallbackCount} variant${fallbackCount === 1 ? "" : "s"}`
      : null;
  }
  return entries
    .sort(([, left], [, right]) => right - left)
    .map(([relation, count]) => `${count} ${relation.replaceAll("_", " ")}`)
    .join(" · ");
}


export function usePriorityReleases(
  workspaceId?: string,
  limit = 50,
  priorityOnly = false,
) {
  return useQuery({
    queryKey: [
      "releases",
      "priority",
      workspaceId ?? "public",
      limit,
      priorityOnly,
    ],
    queryFn: () => {
      const params = new URLSearchParams({
        limit: String(limit),
      });
      if (priorityOnly) {
        params.set("priority_only", "true");
      }
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
