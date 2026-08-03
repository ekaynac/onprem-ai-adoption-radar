import type { SourceHealthRecord } from "../catalog/catalogQueries";


export function isSourceHealthy(source: SourceHealthRecord): boolean {
  if (source.circuit_open_until || source.consecutive_failures > 0) {
    return false;
  }
  if (source.status) {
    return ["ok", "empty"].includes(source.status);
  }
  return Boolean(source.last_success_at);
}
