import type { paths } from "./generated/schema";


export type ApiPaths = paths;

type StaticSnapshot = {
  schema_version: string;
  generated_at: string;
  releases: Array<Record<string, unknown>>;
  models: Array<Record<string, unknown>>;
  platforms: Array<Record<string, unknown>>;
  hardware: Array<Record<string, unknown>>;
  research: Array<Record<string, unknown>>;
  events: Array<Record<string, unknown>>;
  source_health: Record<string, unknown>;
};

let snapshotPromise: Promise<StaticSnapshot> | undefined;


function catalogItem(model: Record<string, unknown>) {
  const releaseId = String(model.release_id);
  const ring = model.public_ring ?? null;
  return {
    release_id: releaseId,
    name: model.name,
    category: model.category,
    lane: model.lane,
    lifecycle: model.lifecycle,
    first_observed_at: model.first_observed_at,
    matched_terms: [],
    public_recommendation: {
      release_id: releaseId,
      workspace_id: null,
      ring,
      public_ring: ring,
      reasons: model.reasons ?? [],
      assumptions: [],
      evidence_ids: model.evidence_ids ?? [],
      changed_factors: [],
      computation_version: "public-snapshot-v1",
    },
    workspace_recommendation: null,
  };
}


export function projectStaticRequest(
  path: string,
  snapshot: StaticSnapshot,
): unknown {
  const url = new URL(path, "https://static.radar.invalid");
  if (url.pathname === "/api/v1/releases") {
    return { items: snapshot.releases, next_cursor: null };
  }
  if (url.pathname.startsWith("/api/v1/releases/")) {
    const releaseId = decodeURIComponent(
      url.pathname.slice("/api/v1/releases/".length),
    );
    return snapshot.releases.find(
      (item) => item.release_id === releaseId,
    );
  }
  if (url.pathname === "/api/v1/catalog") {
    const query = (url.searchParams.get("q") ?? "").toLocaleLowerCase();
    const category = url.searchParams.get("category");
    const lifecycle = url.searchParams.get("lifecycle");
    const items = snapshot.models
      .map(catalogItem)
      .filter((item) => {
        const haystack = `${item.name} ${item.release_id}`.toLocaleLowerCase();
        return (
          (!query || haystack.includes(query)) &&
          (!category || item.category === category) &&
          (!lifecycle || item.lifecycle === lifecycle)
        );
      });
    return { items, next_cursor: null };
  }
  if (url.pathname.startsWith("/api/v1/catalog/")) {
    const releaseId = decodeURIComponent(
      url.pathname.slice("/api/v1/catalog/".length),
    );
    const model = snapshot.models.find(
      (item) => item.release_id === releaseId,
    );
    if (!model) return undefined;
    return {
      release: catalogItem(model),
      claims: [],
      compatibility: [],
      qualification: null,
    };
  }
  if (url.pathname === "/api/v1/operations") {
    return snapshot.source_health;
  }
  if (url.pathname === "/api/v1/operations/reviews") {
    return [];
  }
  if (url.pathname === "/api/v1/workspaces") {
    return [];
  }
  if (url.pathname === "/api/v1/integrations/public-snapshot") {
    return snapshot;
  }
  throw new Error(`Static snapshot does not project ${url.pathname}`);
}


async function staticApiFetch<T>(path: string): Promise<T> {
  snapshotPromise ??= fetch(
    new URL("./data/public-snapshot.v1.json", document.baseURI),
  ).then(async (response) => {
    if (!response.ok) {
      throw new Error(`Public snapshot unavailable: ${response.status}`);
    }
    return response.json() as Promise<StaticSnapshot>;
  });
  const result = projectStaticRequest(path, await snapshotPromise);
  if (result === undefined) {
    throw new Error("Entity is absent from the public snapshot");
  }
  return result as T;
}


export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  workspaceId?: string,
): Promise<T> {
  if (import.meta.env.MODE === "static") {
    return staticApiFetch<T>(path);
  }
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (workspaceId) {
    headers.set("X-Workspace-Id", workspaceId);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    throw new Error(`${response.status} ${await response.text()}`);
  }
  return response.json() as Promise<T>;
}
