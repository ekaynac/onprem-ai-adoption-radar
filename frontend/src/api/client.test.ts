import {
  loadStaticCatalogModels,
  mergeCatalogModels,
  projectStaticRequest,
} from "./client";


test("projects the public snapshot through the REST-shaped client", () => {
  const snapshot = {
    schema_version: "1.0",
    generated_at: "2026-07-30T10:00:00Z",
    releases: [{ release_id: "release:kimi-k3", name: "Kimi K3" }],
    models: [
      {
        release_id: "release:kimi-k3",
        name: "Kimi K3",
        category: "text_reasoning",
        lane: "deployable_onprem",
        lifecycle: "verified",
        first_observed_at: "2026-07-30T10:00:00Z",
        public_ring: "pilot",
        reasons: ["Verified artifact"],
        evidence_ids: ["evidence:one"],
        source_url: "https://huggingface.co/moonshotai/Kimi-K3",
        profile: { hf_repo: "moonshotai/Kimi-K3" },
        claims: [
          {
            predicate: "hf_repo",
            state: "candidate",
            value: "moonshotai/Kimi-K3",
          },
        ],
      },
    ],
    projects: [],
    model_candidates: [],
    platforms: [],
    hardware: [],
    research: [],
    events: [],
    source_health: {
      source_health: [],
      open_review_count: 0,
      stale_claim_count: 0,
    },
  };

  expect(projectStaticRequest("/api/v1/releases", snapshot)).toEqual({
    items: snapshot.releases,
    next_cursor: null,
  });
  expect(
    projectStaticRequest("/api/v1/catalog?q=kimi", snapshot),
  ).toMatchObject({
    items: [
      {
        release_id: "release:kimi-k3",
        public_recommendation: { ring: "pilot" },
      },
    ],
  });
  expect(
    projectStaticRequest("/api/v1/catalog/release%3Akimi-k3", snapshot),
  ).toMatchObject({
    profile: { hf_repo: "moonshotai/Kimi-K3" },
    source_url: "https://huggingface.co/moonshotai/Kimi-K3",
    claims: [{ predicate: "hf_repo", value: "moonshotai/Kimi-K3" }],
  });
});


test("filters and ranks priority releases before applying the response cap", () => {
  const lowConfidence = Array.from({ length: 50 }, (_, index) => ({
    release_id: `release:low-${index}`,
    name: `Low ${index}`,
    confidence: 0.45,
    review_status: "clear",
    released_at: "2026-08-03T10:00:00Z",
  }));
  const authority = {
    release_id: "release:authority",
    name: "Authoritative release",
    confidence: 0.9,
    review_status: "clear",
    released_at: "2026-08-02T10:00:00Z",
  };
  const snapshot = {
    schema_version: "1.0",
    generated_at: "2026-08-03T10:00:00Z",
    releases: [...lowConfidence, authority],
    models: [], projects: [], model_candidates: [], platforms: [], hardware: [],
    research: [], events: [], source_health: {},
  };

  const result = projectStaticRequest(
    "/api/v1/releases?priority_only=true&limit=1",
    snapshot,
  ) as { items: Array<{ release_id: string }> };

  expect(result.items.map((item) => item.release_id)).toEqual(["release:authority"]);
});


test("merges compact models with detailed snapshot data winning", () => {
  const compact = [
    {
      release_id: "release:one",
      name: "Compact name",
      first_observed_at: "2026-07-30T10:00:00Z",
      claims: [],
    },
    {
      release_id: "release:two",
      name: "Second model",
      first_observed_at: "2026-07-29T10:00:00Z",
    },
  ];
  const detailed = [
    {
      release_id: "release:one",
      name: "Detailed name",
      first_observed_at: "2026-07-30T10:00:00Z",
      claims: [{ predicate: "parameters", value: 10 }],
    },
  ];

  expect(mergeCatalogModels(compact, detailed)).toEqual([
    detailed[0],
    compact[1],
  ]);
});


test("filters the complete catalog before capping rendered rows", () => {
  const models = Array.from({ length: 650 }, (_, index) => ({
    release_id: `release:model-${index}`,
    name: index === 649 ? "Needle Model" : `Model ${index}`,
    category: "text_reasoning",
    lane: "deployable_onprem",
    lifecycle: "detected",
    first_observed_at: `2026-07-30T${String(index % 24).padStart(2, "0")}:00:00Z`,
  }));
  const snapshot = {
    schema_version: "1.0",
    generated_at: "2026-07-30T10:00:00Z",
    releases: [],
    models: [],
    projects: [],
    model_candidates: [],
    platforms: [],
    hardware: [],
    research: [],
    events: [],
    source_health: {},
  };

  const all = projectStaticRequest("/api/v1/catalog", snapshot, models) as {
    items: Array<{ release_id: string }>;
    next_cursor: string | null;
  };
  const search = projectStaticRequest(
    "/api/v1/catalog?q=needle",
    snapshot,
    models,
  ) as { items: Array<{ release_id: string }>; next_cursor: string | null };

  expect(all.items).toHaveLength(500);
  expect(all.next_cursor).toBe("release:model-499");
  expect(search.items.map((item) => item.release_id)).toEqual([
    "release:model-649",
  ]);
  expect(search.next_cursor).toBeNull();
});


test("applies lane and canonical-field search before the render cap", () => {
  const models = Array.from({ length: 650 }, (_, index) => ({
    release_id: `release:model-${index}`,
    name: `Model ${index}`,
    category: index === 649 ? "multimodal" : "text_reasoning",
    lane: index === 649 ? "market_reference" : "deployable_onprem",
    lifecycle: index === 649 ? "verified" : "detected",
    first_observed_at: "2026-07-30T10:00:00Z",
  }));
  const snapshot = {
    schema_version: "1.0",
    generated_at: "2026-07-30T10:00:00Z",
    releases: [],
    models: [],
    projects: [],
    model_candidates: [],
    platforms: [],
    hardware: [],
    research: [],
    events: [],
    source_health: {},
  };

  const lane = projectStaticRequest(
    "/api/v1/catalog?lane=market_reference",
    snapshot,
    models,
  ) as { items: Array<{ release_id: string }> };
  const canonicalSearch = projectStaticRequest(
    "/api/v1/catalog?q=multimodal+market_reference+verified",
    snapshot,
    models,
  ) as { items: Array<{ release_id: string }> };

  expect(lane.items.map((item) => item.release_id)).toEqual([
    "release:model-649",
  ]);
  expect(canonicalSearch.items.map((item) => item.release_id)).toEqual([
    "release:model-649",
  ]);
});


test("applies metadata filters across the complete catalog before capping", () => {
  const models = Array.from({ length: 650 }, (_, index) => ({
    release_id: `release:model-${index}`,
    name: `Model ${index}`,
    category: "text_reasoning",
    lane: "deployable_onprem",
    lifecycle: "detected",
    first_observed_at: "2026-07-30T10:00:00Z",
    released_at: index === 649 ? "2026-08-03T10:00:00Z" : "2026-07-30T10:00:00Z",
    profile: {
      publisher: index === 649 ? "publisher:moonshot-ai" : "publisher:other",
      license: index === 649 ? "modified-mit" : "apache-2.0",
      modality: index === 649 ? "image-text-to-text" : "text-generation",
      hardware_tier: index === 649 ? "datacenter" : "workstation",
      library_name: index === 649 ? "transformers" : "llama.cpp",
    },
  }));
  const snapshot = {
    schema_version: "1.0",
    generated_at: "2026-08-03T10:15:00Z",
    releases: [], models: [], projects: [], model_candidates: [], platforms: [],
    hardware: [], research: [], events: [], source_health: {},
  };

  const result = projectStaticRequest(
    "/api/v1/catalog?publisher=publisher%3Amoonshot-ai&license=modified-mit&modality=image-text-to-text&hardware=datacenter&platform=transformers&freshness=fresh",
    snapshot,
    models,
  ) as { items: Array<{ release_id: string }> };
  const facets = projectStaticRequest(
    "/api/v1/catalog/facets",
    snapshot,
    models,
  ) as Record<string, string[]>;

  expect(result.items.map((item) => item.release_id)).toEqual(["release:model-649"]);
  expect(facets.publisher).toEqual(["publisher:moonshot-ai", "publisher:other"]);
  expect(facets.license).toEqual(["apache-2.0", "modified-mit"]);
  expect(facets.platform).toEqual(["llama.cpp", "transformers"]);
});


test("falls back to detailed snapshot models when the index is unavailable", async () => {
  const snapshot = {
    schema_version: "1.0",
    generated_at: "2026-07-30T10:00:00Z",
    releases: [],
    models: [{ release_id: "release:fallback", name: "Fallback" }],
    model_index: {
      manifest_path: "data/model-index.v1.json",
      total: 10,
    },
    projects: [],
    model_candidates: [],
    platforms: [],
    hardware: [],
    research: [],
    events: [],
    source_health: {},
  };
  const unavailable = async () => new Response(null, { status: 404 });

  await expect(loadStaticCatalogModels(snapshot, unavailable)).resolves.toEqual(
    snapshot.models,
  );
});
