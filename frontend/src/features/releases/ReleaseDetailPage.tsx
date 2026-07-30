import { Link, useParams } from "react-router-dom";

import { StatusBadge, type IntelligenceStatus } from "../../design/StatusBadge";
import { useReleaseDetail } from "./releaseQueries";


export function ReleaseDetailPage() {
  const { releaseId = "" } = useParams();
  const release = useReleaseDetail(releaseId);

  if (release.isLoading) {
    return <div className="loading-grid" aria-label="Loading release"><span /></div>;
  }
  if (release.isError || !release.data) {
    return (
      <div className="error-state" role="alert">
        <strong>Release detail unavailable</strong>
        <button type="button" onClick={() => void release.refetch()}>Try again</button>
      </div>
    );
  }

  const item = release.data;
  const citations = item.citations ?? [];
  return (
    <section className="page-stack" aria-labelledby="release-title">
      <Link to="/releases" className="text-link">← Release stream</Link>
      <header className="detail-hero">
        <div>
          <p className="eyebrow">{item.category.replaceAll("_", " ")}</p>
          <h1 id="release-title">{item.name}</h1>
          <p className="lede">
            {item.lane.replaceAll("_", " ")} · observed{" "}
            {new Date(item.first_observed_at).toLocaleString()}
          </p>
        </div>
        <StatusBadge status={item.lifecycle as IntelligenceStatus} />
      </header>
      <div className="detail-grid">
        <section className="panel">
          <p className="eyebrow">Lifecycle timeline</p>
          <ol className="lifecycle-track">
            {["detected", "verified", "qualified", "recommended"].map((state) => (
              <li className={state === item.lifecycle ? "current" : ""} key={state}>
                {state}
              </li>
            ))}
          </ol>
        </section>
        <section className="panel">
          <p className="eyebrow">Decision evidence</p>
          <dl className="detail-facts">
            <div><dt>Confidence</dt><dd>{Math.round(item.confidence * 100)}%</dd></div>
            <div><dt>Freshness</dt><dd>{item.freshness}</dd></div>
            <div><dt>Review</dt><dd>{item.review_status}</dd></div>
          </dl>
        </section>
      </div>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Citations</p>
            <h2>Trace every material claim</h2>
          </div>
        </div>
        {citations.length ? (
          <ul className="citation-list">
            {citations.map((citation) => (
              <li key={citation.evidence_id}>
                <a href={citation.url} rel="noreferrer" target="_blank">
                  {citation.strength.replaceAll("_", " ")}
                </a>
                <time dateTime={citation.retrieved_at}>
                  {new Date(citation.retrieved_at).toLocaleDateString()}
                </time>
              </li>
            ))}
          </ul>
        ) : (
          <div className="empty-state compact">
            <strong>No claim citations attached yet</strong>
            <span>The release remains visible at its current lifecycle state.</span>
          </div>
        )}
      </section>
    </section>
  );
}
