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
      {snapshot.isLoading ? (
        <div className="loading-grid" aria-label="Loading platforms"><span /></div>
      ) : (
      <div className="entity-card-grid">
        {items.map((item) => (
          <Link
            className="panel intelligence-card entity-link-card"
            key={item.id}
            to={`/platforms/${encodeURIComponent(item.id)}`}
          >
            <div className="card-topline"><span>Serving platform</span><span>Checked {item.checked_at ? new Date(item.checked_at).toLocaleString() : "pending"}</span></div>
            <h2>{item.name}</h2>
            <p className="card-summary">{item.notes || "Capability evidence available."}</p>
            <dl className="mini-facts">
              <div><dt>Hardware</dt><dd>{Object.values(item.hardware ?? {}).filter((value) => value === "yes").length} confirmed</dd></div>
              <div><dt>Features</dt><dd>{Object.values(item.features ?? {}).filter((value) => value === "yes").length} confirmed</dd></div>
              <div><dt>Sources</dt><dd>{(item.sources ?? []).length}</dd></div>
            </dl>
            <span className="text-link">Open compatibility record →</span>
          </Link>
        ))}
      </div>
      )}
    </section>
  );
}
