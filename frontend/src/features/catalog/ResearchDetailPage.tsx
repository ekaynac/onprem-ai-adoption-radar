import { Link, useParams } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


export function ResearchDetailPage() {
  const { researchId = "" } = useParams();
  const snapshot = usePublicSnapshot();
  const research = snapshot.data?.research.find((item) => item.id === researchId);

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading research"><span /></div>;
  }
  if (!research) {
    return <div className="empty-state"><strong>Research not found</strong><Link to="/research">Return to research</Link></div>;
  }
  return (
    <section className="page-stack" aria-labelledby="research-title">
      <Link className="text-link" to="/research">← Research</Link>
      <header className="detail-hero">
        <div>
          <p className="eyebrow">{research.domain.replaceAll("_", " ")}</p>
          <h1 id="research-title">{research.name}</h1>
          <p className="lede">{research.onprem_impact.replaceAll("_", " ")}</p>
        </div>
        {research.ring && <span className={`ring-pill ring-${research.ring}`}>{research.ring}</span>}
      </header>
      <div className="detail-grid">
        <section className="panel">
          <p className="eyebrow">Operational consequence</p>
          <h2>Why architects should care</h2>
          <p className="body-copy">{research.notes ?? "No operational note recorded."}</p>
          <dl className="detail-facts stacked">
            <div><dt>Open code</dt><dd>{research.open_code ? "Yes" : "No"}</dd></div>
            <div><dt>Peer reviewed</dt><dd>{research.peer_reviewed === null ? "Unknown" : research.peer_reviewed ? "Yes" : "No"}</dd></div>
            <div><dt>Citations</dt><dd>{research.citation_count?.toLocaleString() ?? "Unknown"}</dd></div>
            <div><dt>Momentum</dt><dd>{research.momentum_direction ?? "Unknown"}</dd></div>
            <div><dt>Score</dt><dd>{research.score?.toFixed(2) ?? "Unrated"}</dd></div>
          </dl>
        </section>
        <aside className="panel">
          <p className="eyebrow">Adoption evidence</p>
          <h2>Implementations</h2>
          {research.resolved_implementations.length ? (
            <ul className="detail-list">
              {research.resolved_implementations.map((item) => (
                <li key={`${item.kind}:${item.ref}`}>
                  <strong>{item.ref}</strong> · {item.kind}
                  {item.ring ? ` · ${item.ring}` : ""}
                </li>
              ))}
            </ul>
          ) : (
            <p className="body-copy">No tracked implementation yet.</p>
          )}
        </aside>
      </div>
      <section className="panel">
        <p className="eyebrow">Primary research</p>
        <h2>Papers</h2>
        <div className="paper-list">
          {research.papers.map((paper) => (
            <a
              href={`https://arxiv.org/abs/${paper.arxiv_id}`}
              key={paper.arxiv_id}
              rel="noreferrer"
              target="_blank"
            >
              <span>{paper.role} · {paper.published ?? "date unknown"}</span>
              <strong>{paper.title}</strong>
              <small>arXiv:{paper.arxiv_id} ↗</small>
            </a>
          ))}
        </div>
      </section>
    </section>
  );
}
