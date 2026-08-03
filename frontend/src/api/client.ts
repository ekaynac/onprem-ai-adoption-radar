import type { paths } from "./generated/schema";


export type ApiPaths = paths;

type StaticSnapshot = {
  schema_version: string;
  generated_at: string;
  model_index?: {
    manifest_path: string;
    total: number;
  };
  project_data?: {
    mode: "live_projection" | "last_published_baseline" | "unavailable";
    generated_at?: string | null;
  };
  releases: Array<Record<string, unknown>>;
  models: Array<Record<string, unknown>>;
  projects: Array<Record<string, unknown>>;
  model_candidates: Array<Record<string, unknown>>;
  platforms: Array<Record<string, unknown>>;
  hardware: Array<Record<string, unknown>>;
  research: Array<Record<string, unknown>>;
  latest_digest?: {
    generated_at: string;
    html_url: string;
    card_url?: string;
  } | null;
  events: Array<Record<string, unknown>>;
  source_health: Record<string, unknown>;
};

type StaticModelIndexManifest = {
  schema_version: string;
  generated_at: string;
  total: number;
  shard_size: number;
  shards: Array<{ path: string; count: number }>;
};

let snapshotPromise: Promise<StaticSnapshot> | undefined;
let catalogModelsPromise: Promise<Array<Record<string, unknown>>> | undefined;


function modelTimestamp(model: Record<string, unknown>): number {
  const value = Date.parse(String(model.first_observed_at ?? ""));
  return Number.isNaN(value) ? 0 : value;
}


export function mergeCatalogModels(
  compact: Array<Record<string, unknown>>,
  detailed: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const byRelease = new Map<string, Record<string, unknown>>();
  for (const model of compact) {
    byRelease.set(String(model.release_id), model);
  }
  for (const model of detailed) {
    byRelease.set(String(model.release_id), model);
  }
  return [...byRelease.values()].sort((left, right) => {
    const timeDifference = modelTimestamp(right) - modelTimestamp(left);
    if (timeDifference !== 0) return timeDifference;
    return String(left.release_id).localeCompare(String(right.release_id));
  });
}


export async function loadStaticCatalogModels(
  snapshot: StaticSnapshot,
  fetcher: typeof fetch = fetch,
): Promise<Array<Record<string, unknown>>> {
  const reference = snapshot.model_index;
  if (!reference) return snapshot.models;
  try {
    const manifestResponse = await fetcher(
      new URL(`./${reference.manifest_path}`, document.baseURI),
    );
    if (!manifestResponse.ok) throw new Error("Model index manifest unavailable");
    const manifest = (await manifestResponse.json()) as StaticModelIndexManifest;
    const shardPayloads = await Promise.all(
      manifest.shards.map(async (shard) => {
        const response = await fetcher(
          new URL(`./${shard.path}`, document.baseURI),
        );
        if (!response.ok) throw new Error(`Model index shard unavailable: ${shard.path}`);
        const payload = (await response.json()) as {
          items?: Array<Record<string, unknown>>;
        };
        if (!Array.isArray(payload.items) || payload.items.length !== shard.count) {
          throw new Error(`Invalid model index shard: ${shard.path}`);
        }
        return payload.items;
      }),
    );
    const compact = shardPayloads.flat();
    if (compact.length !== manifest.total || manifest.total !== reference.total) {
      throw new Error("Model index count mismatch");
    }
    return mergeCatalogModels(compact, snapshot.models);
  } catch {
    return snapshot.models;
  }
}


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
  catalogModels: Array<Record<string, unknown>> = snapshot.models,
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
    const filtered = catalogModels
      .map(catalogItem)
      .filter((item) => {
        const haystack = `${item.name} ${item.release_id}`.toLocaleLowerCase();
        return (
          (!query || haystack.includes(query)) &&
          (!category || item.category === category) &&
          (!lifecycle || item.lifecycle === lifecycle)
        );
      });
    const items = filtered.slice(0, 500);
    return {
      items,
      next_cursor:
        filtered.length > items.length
          ? String(items.at(-1)?.release_id ?? "")
          : null,
    };
  }
  if (url.pathname.startsWith("/api/v1/catalog/")) {
    const releaseId = decodeURIComponent(
      url.pathname.slice("/api/v1/catalog/".length),
    );
    const model = catalogModels.find(
      (item) => item.release_id === releaseId,
    );
    if (!model) return undefined;
    return {
      release: catalogItem(model),
      claims: model.claims ?? [],
      compatibility: [],
      qualification: null,
      profile: model.profile ?? null,
      source_url: model.source_url ?? null,
      source_strength: model.source_strength ?? null,
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
  const snapshot = await snapshotPromise;
  const pathname = new URL(path, "https://static.radar.invalid").pathname;
  const needsCatalog = pathname === "/api/v1/catalog"
    || pathname.startsWith("/api/v1/catalog/");
  const catalogModels = needsCatalog
    ? await (catalogModelsPromise ??= loadStaticCatalogModels(snapshot))
    : snapshot.models;
  const result = projectStaticRequest(path, snapshot, catalogModels);
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
