import { describe, expect, test } from "vitest";

import { isSourceHealthy } from "./sourceHealth";


describe("isSourceHealthy", () => {
  test("accepts successful incremental polls with no new items", () => {
    expect(isSourceHealthy({
      source_id: "rss-ollama-blog",
      status: "empty",
      consecutive_failures: 0,
      last_success_at: "2026-08-03T11:08:54Z",
    })).toBe(true);
  });

  test("accepts successful intelligence adapters without a legacy status", () => {
    expect(isSourceHealthy({
      source_id: "huggingface",
      consecutive_failures: 0,
      last_success_at: "2026-08-03T11:06:04Z",
    })).toBe(true);
  });

  test("rejects partial, failed, stale, and open-circuit sources", () => {
    expect(isSourceHealthy({
      source_id: "partial",
      status: "partial",
      consecutive_failures: 0,
    })).toBe(false);
    expect(isSourceHealthy({
      source_id: "failed",
      status: "error",
      consecutive_failures: 1,
    })).toBe(false);
    expect(isSourceHealthy({
      source_id: "stale",
      status: "stale",
      consecutive_failures: 0,
    })).toBe(false);
    expect(isSourceHealthy({
      source_id: "open",
      status: "ok",
      consecutive_failures: 0,
      circuit_open_until: "2026-08-04T00:00:00Z",
    })).toBe(false);
  });
});
