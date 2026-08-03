import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { apiFetch } from "../../api/client";
import type { components } from "../../api/generated/schema";
import {
  usePublicSnapshot,
  type SourceHealthRecord,
} from "../catalog/catalogQueries";


type Operations = Omit<components["schemas"]["OperationsSnapshot"], "source_health"> & {
  source_health: SourceHealthRecord[];
};


export function SourceHealthPage({ staticMode = false }: { staticMode?: boolean }) {
  const operations = useQuery({
    queryKey: ["operations", "health"],
    queryFn: ({ signal }) =>
      apiFetch<Operations>("/api/v1/operations", { signal }),
    refetchInterval: 60_000,
  });
  const snapshot = usePublicSnapshot();
  const quality = snapshot.data?.quality;
  const sourceCoverage = snapshot.data?.source_coverage ?? [];
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Monitor · Operations</p>
          <h1>Freshness, source health, and exception pressure</h1>
        </div>
        {!staticMode && (
          <Link className="primary-link" to="/operations/reviews">
            Review queue ({operations.data?.open_review_count ?? 0})
          </Link>
        )}
      </header>
      <div className="ops-stats">
        <article className="panel"><strong>{operations.data?.stale_claim_count ?? 0}</strong><span>stale claims</span></article>
        <article className="panel"><strong>{operations.data?.open_review_count ?? 0}</strong><span>review exceptions</span></article>
        <article className="panel"><strong>{operations.data?.source_health?.length ?? 0}</strong><span>sources monitored</span></article>
      </div>
      {quality && (
        <section className="page-stack" aria-labelledby="quality-coverage-heading">
          <header className="section-heading">
            <div>
              <p className="eyebrow">Evidence coverage</p>
              <h2 id="quality-coverage-heading">Data quality</h2>
            </div>
          </header>
          <div className="ops-stats">
            <article className="panel">
              <strong>{quality.models?.verified_or_better ?? 0}/{quality.models?.total ?? 0}</strong>
              <span>verified models</span>
            </article>
            <article className="panel">
              <strong>{quality.hardware?.with_spec_url ?? 0}/{quality.hardware?.total ?? 0}</strong>
              <span>hardware with primary specs</span>
            </article>
            <article className="panel">
              <strong>{quality.projects?.with_repository ?? 0}/{quality.projects?.total ?? 0}</strong>
              <span>projects with repositories</span>
            </article>
            <article className="panel">
              <strong>{quality.research?.with_implementations ?? 0}/{quality.research?.total ?? 0}</strong>
              <span>research with implementations</span>
            </article>
          </div>
        </section>
      )}
      {sourceCoverage.length > 0 && (
        <section className="page-stack" aria-labelledby="source-coverage-heading">
          <header className="section-heading">
            <div>
              <p className="eyebrow">Ingestion contracts</p>
              <h2 id="source-coverage-heading">Source coverage</h2>
            </div>
          </header>
          <div className="release-table-wrap">
            <table className="release-table">
              <thead>
                <tr><th>Family</th><th>Adapter</th><th>State</th></tr>
              </thead>
              <tbody>
                {sourceCoverage.map((source) => (
                  <tr key={source.id}>
                    <td>{source.id}</td>
                    <td>{source.type}</td>
                    <td>{source.enabled ? "Active" : "Contract verification pending"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
      <div className="release-table-wrap">
        <table className="release-table">
          <thead>
            <tr><th>Source</th><th>Status</th><th>Last success</th><th>Failures</th><th>Latency</th><th>Items</th><th>Circuit</th></tr>
          </thead>
          <tbody>
            {(operations.data?.source_health ?? []).map((source) => (
              <tr key={source.source_id}>
                <td>{source.source_id}</td>
                <td>{source.status ?? "Unknown"}</td>
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
