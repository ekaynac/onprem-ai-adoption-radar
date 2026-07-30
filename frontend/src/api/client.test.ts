import { projectStaticRequest } from "./client";


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
      },
    ],
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
});
