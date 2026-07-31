import { Link } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


export function PlatformsPage() {
  const snapshot = usePublicSnapshot();
  const items = snapshot.data?.platforms ?? [];
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Platforms</p>
          <h1>Serving and orchestration platforms</h1>
          <p className="lede">Version-aware support grounded in documentation and tests.</p>
        </div>
      </header>
      <div className="entity-card-grid">
        {items.map((item, index) => (
          <Link
            className="panel entity-link-card"
            key={String(item.id ?? index)}
            to={`/platforms/${encodeURIComponent(String(item.id))}`}
          >
            <p className="eyebrow">Platform</p>
            <strong>{String(item.name ?? item.id)}</strong>
            <span>Verified {String(item.verified_at ?? "unknown")}</span>
          </Link>
        ))}
      </div>
    </section>
  );
}
