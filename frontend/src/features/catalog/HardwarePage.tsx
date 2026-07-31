import { usePublicSnapshot } from "./catalogQueries";


export function HardwarePage() {
  const snapshot = usePublicSnapshot();
  const items = snapshot.data?.hardware ?? [];
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Hardware</p>
          <h1>Infrastructure capacity catalog</h1>
          <p className="lede">Accelerators, memory topology, and deployment-fit evidence.</p>
        </div>
      </header>
      {snapshot.isLoading ? (
        <div className="loading-grid"><span /></div>
      ) : items.length ? (
        <div className="entity-card-grid">
          {items.map((item, index) => (
            <article className="panel" key={String(item.id ?? index)}>
              <strong>{String(item.name ?? item.id)}</strong>
              <pre className="record-view" tabIndex={0}>
                {JSON.stringify(item, null, 2)}
              </pre>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No canonical hardware observations yet</strong>
          <span>Add a workspace device or ingest a verified hardware registry.</span>
        </div>
      )}
    </section>
  );
}
