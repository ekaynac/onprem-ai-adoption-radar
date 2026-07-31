import { Link, useParams } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


export function PlatformDetailPage() {
  const { platformId = "" } = useParams();
  const snapshot = usePublicSnapshot();
  const platform = snapshot.data?.platforms.find(
    (item) => item.id === platformId,
  );

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading platform"><span /></div>;
  }
  if (!platform) {
    return (
      <div className="empty-state">
        <strong>Platform not found</strong>
        <Link to="/platforms">Return to platforms</Link>
      </div>
    );
  }
  return (
    <section className="page-stack">
      <Link className="text-link" to="/platforms">← Platforms</Link>
      <header className="detail-hero">
        <div>
          <p className="eyebrow">Serving platform</p>
          <h1>{platform.name}</h1>
          <p className="lede">
            Matrix verified {platform.verified_at ?? platform.verified ?? "unknown"}
            {" · "}
            source check {platform.checked_at ? new Date(platform.checked_at).toLocaleString() : "pending"}
            {platform.verification_status ? ` (${platform.verification_status})` : ""}
          </p>
        </div>
      </header>
      <div className="detail-grid">
        <section className="panel">
          <p className="eyebrow">Hardware scope</p>
          <h2>Supported accelerator families</h2>
          <div className="support-grid">
            {Object.entries(platform.hardware ?? {}).map(([name, support]) => (
              <div key={name}><span>{name.replaceAll("_", " ")}</span><strong className={`support-${support}`}>{support}</strong></div>
            ))}
          </div>
        </section>
        <aside className="panel">
          <p className="eyebrow">Official project</p>
          <h2>{platform.name}</h2>
          <p className="body-copy">{platform.notes || "No additional platform note recorded."}</p>
          <a className="primary-link inline-link" href={platform.repo_url} rel="noreferrer" target="_blank">Open repository ↗</a>
        </aside>
      </div>
      <section className="panel">
        <p className="eyebrow">Serving capability</p>
        <h2>Feature matrix</h2>
        <div className="support-grid feature-support-grid">
          {Object.entries(platform.features ?? {}).map(([name, support]) => (
            <div key={name}><span>{name.replaceAll("_", " ")}</span><strong className={`support-${support}`}>{support}</strong></div>
          ))}
        </div>
      </section>
      <section className="panel">
        <p className="eyebrow">Evidence</p>
        <h2>Verification sources</h2>
        <div className="evidence-links">
          {(platform.sources ?? []).map((source) => (
            <a href={source} key={source} rel="noreferrer" target="_blank">{source}</a>
          ))}
        </div>
      </section>
    </section>
  );
}
