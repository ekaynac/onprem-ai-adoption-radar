import { Link, useParams } from "react-router-dom";

import { StatusBadge, type IntelligenceStatus } from "../../design/StatusBadge";
import { useActiveWorkspaceId } from "../releases/releaseQueries";
import { useCatalogDetail } from "./catalogQueries";


function ClaimStatus({ state }: { state: string }) {
  const status: IntelligenceStatus =
    state === "verified"
      ? "verified"
      : state === "stale"
        ? "stale"
        : state === "conflicting"
          ? "review"
          : "unknown";
  return <StatusBadge status={status} />;
}


function formatValue(value: unknown, unit?: string | null) {
  if (value === null || value === undefined) return "Not available";
  const rendered =
    typeof value === "object" ? JSON.stringify(value) : String(value);
  return unit ? `${rendered} ${unit}` : rendered;
}


export function ModelDetailPage() {
  const { releaseId = "" } = useParams();
  const workspaceId = useActiveWorkspaceId();
  const detail = useCatalogDetail(releaseId, workspaceId);

  if (detail.isLoading) {
    return <div className="loading-grid" aria-label="Loading model"><span /></div>;
  }
  if (detail.isError || !detail.data) {
    return (
      <div className="error-state" role="alert">
        <strong>Model intelligence unavailable</strong>
        <button type="button" onClick={() => void detail.refetch()}>Try again</button>
      </div>
    );
  }

  const { release, claims, compatibility, qualification } = detail.data;
  return (
    <section className="page-stack" aria-labelledby="model-title">
      <Link className="text-link" to="/catalog">← Unified catalog</Link>
      <header className="detail-hero">
        <div>
          <p className="eyebrow">{release.category.replaceAll("_", " ")}</p>
          <h1 id="model-title">{release.name}</h1>
          <p className="lede">{release.lane.replaceAll("_", " ")}</p>
        </div>
        <StatusBadge status={release.lifecycle} />
      </header>
      <div className="detail-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Verified specification</p>
              <h2>Claims and provenance</h2>
            </div>
          </div>
          <div className="claim-grid">
            {claims.map((claim) => (
              <article className="claim-card" key={claim.predicate}>
                <div className="claim-heading">
                  <strong>{claim.predicate.replaceAll("_", " ")}</strong>
                  <ClaimStatus state={claim.state} />
                </div>
                <p className="claim-value">
                  {formatValue(claim.value, claim.unit)}
                </p>
                {claim.reason && <p className="claim-reason">{claim.reason}</p>}
                {claim.effective_range && (
                  <p className="claim-meta">Effective {claim.effective_range}</p>
                )}
                <div className="claim-citations">
                  {(claim.citations ?? []).map((citation) => (
                    <a
                      href={citation.url}
                      key={citation.evidence_id}
                      rel="noreferrer"
                      target="_blank"
                    >
                      {citation.label}
                    </a>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
        <aside className="panel">
          <p className="eyebrow">Qualification</p>
          <h2>{qualification?.qualified ? "Qualified" : "Not yet qualified"}</h2>
          <p className="claim-reason">
            {qualification?.reasons?.[0] ??
              "Awaiting sufficient verified deployment evidence."}
          </p>
          <hr />
          <p className="eyebrow">Recommendation</p>
          <strong className="large-posture">
            {release.workspace_recommendation?.ring ??
              release.public_recommendation.ring ??
              "Unrated"}
          </strong>
          <p className="claim-reason">
            {release.lane === "market_reference"
              ? "Market references never receive an on-prem adoption ring."
              : (release.workspace_recommendation?.reasons ??
                  release.public_recommendation.reasons ??
                  [])[0] ?? "No recommendation rationale yet."}
          </p>
        </aside>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Compatibility</p>
            <h2>Version-aware platform support</h2>
          </div>
        </div>
        {compatibility.length ? (
          <table className="compatibility-table">
            <thead>
              <tr>
                <th>Platform</th><th>Version</th><th>Feature</th>
                <th>Support</th><th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {compatibility.map((item) => (
                <tr key={item.id}>
                  <td>{item.platform_id}</td>
                  <td>{item.platform_version}</td>
                  <td>{item.feature}</td>
                  <td>{item.support}</td>
                  <td>{item.evidence_level}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="empty-state compact">
            <strong>No compatibility assertion yet</strong>
            <span>Unknown is preserved until documentation or a test is attached.</span>
          </div>
        )}
      </section>
    </section>
  );
}
