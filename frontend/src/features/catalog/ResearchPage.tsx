import { usePublicSnapshot } from "./catalogQueries";


export function ResearchPage() {
  const snapshot = usePublicSnapshot();
  const items = snapshot.data?.research ?? [];
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Research</p>
          <h1>Techniques with operational consequence</h1>
          <p className="lede">
            Research enters the command center when it changes an on-prem
            architecture decision.
          </p>
        </div>
      </header>
      {items.length ? (
        <div className="entity-card-grid">
          {items.map((item, index) => (
            <article className="panel" key={String(item.id ?? index)}>
              <strong>{String(item.name ?? item.title ?? item.id)}</strong>
              <pre className="record-view">{JSON.stringify(item, null, 2)}</pre>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No research changes in the public snapshot</strong>
          <span>The existing research archive remains available during migration.</span>
        </div>
      )}
    </section>
  );
}
