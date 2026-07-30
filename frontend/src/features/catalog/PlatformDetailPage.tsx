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
          <h1>{String(platform.name)}</h1>
          <p className="lede">Verified {String(platform.verified_at ?? "unknown")}</p>
        </div>
      </header>
      <section className="panel">
        <p className="eyebrow">Canonical platform record</p>
        <pre className="record-view">{JSON.stringify(platform, null, 2)}</pre>
      </section>
    </section>
  );
}
