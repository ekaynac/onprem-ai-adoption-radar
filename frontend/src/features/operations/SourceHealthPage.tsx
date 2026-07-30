import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";


type Operations = components["schemas"]["OperationsSnapshot"];


export function SourceHealthPage() {
  const operations = useQuery({
    queryKey: ["operations", "health"],
    queryFn: ({ signal }) =>
      apiFetch<Operations>("/api/v1/operations", { signal }),
    refetchInterval: 60_000,
  });
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Monitor · Operations</p>
          <h1>Freshness, source health, and exception pressure</h1>
        </div>
        <Link className="primary-link" to="/operations/reviews">
          Review queue ({operations.data?.open_review_count ?? 0})
        </Link>
      </header>
      <div className="ops-stats">
        <article className="panel"><strong>{operations.data?.stale_claim_count ?? 0}</strong><span>stale claims</span></article>
        <article className="panel"><strong>{operations.data?.open_review_count ?? 0}</strong><span>review exceptions</span></article>
        <article className="panel"><strong>{operations.data?.source_health?.length ?? 0}</strong><span>sources monitored</span></article>
      </div>
      <div className="release-table-wrap">
        <table className="release-table">
          <thead>
            <tr><th>Source</th><th>Last success</th><th>Failures</th><th>Latency</th><th>Items</th><th>Circuit</th></tr>
          </thead>
          <tbody>
            {(operations.data?.source_health ?? []).map((source) => (
              <tr key={source.source_id}>
                <td>{source.source_id}</td>
                <td>{source.last_success_at ? new Date(source.last_success_at).toLocaleString() : "Never"}</td>
                <td>{source.consecutive_failures}</td>
                <td>{source.latency_ms ? `${Math.round(source.latency_ms)} ms` : "—"}</td>
                <td>{source.items_count ?? "—"}</td>
                <td>{source.circuit_open_until ? "Open" : "Closed"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
