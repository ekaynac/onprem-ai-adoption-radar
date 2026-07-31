import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


export function ResearchPage() {
  const snapshot = usePublicSnapshot();
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("all");
  const items = useMemo(
    () =>
      (snapshot.data?.research ?? []).filter(
        (item) =>
          (!query ||
            `${item.name} ${item.aliases.join(" ")} ${item.notes ?? ""}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (domain === "all" || item.domain === domain),
      ),
    [domain, query, snapshot.data?.research],
  );
  return (
    <section className="page-stack" aria-labelledby="research-page-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Research</p>
          <h1 id="research-page-title">Techniques with operational consequence</h1>
          <p className="lede">
            Research enters the command center when it changes an on-prem
            architecture decision.
          </p>
        </div>
      </header>
      <div className="compact-filters">
        <label>
          <span>Search research</span>
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Attention, quantization, RAG…" />
        </label>
        <label>
          <span>Domain</span>
          <select value={domain} onChange={(event) => setDomain(event.target.value)}>
            <option value="all">All domains</option>
            <option value="inference">Inference</option>
            <option value="fine_tuning">Fine tuning</option>
            <option value="rag">RAG</option>
            <option value="agent_architecture">Agent architecture</option>
            <option value="safety_sandboxing">Safety & sandboxing</option>
            <option value="orchestration">Orchestration</option>
            <option value="embodied">Embodied AI</option>
          </select>
        </label>
      </div>
      {snapshot.isLoading ? (
        <div className="loading-grid" aria-label="Loading research"><span /></div>
      ) : items.length ? (
        <div className="entity-card-grid">
          {items.map((item) => (
            <article className="panel intelligence-card" key={item.id}>
              <div className="card-topline">
                <span>{item.domain.replaceAll("_", " ")}</span>
                <span>{item.ring ?? "unrated"}</span>
              </div>
              <div>
                <p className="eyebrow">{item.onprem_impact.replaceAll("_", " ")}</p>
                <h2>{item.name}</h2>
                <p className="card-summary">{item.notes ?? "Operational note pending."}</p>
                {item.warnings.map((warning) => (
                  <p className="data-state-note" key={warning}>{warning}</p>
                ))}
              </div>
              <dl className="mini-facts">
                <div><dt>Citations</dt><dd>{item.citation_count?.toLocaleString() ?? "Unknown"}</dd></div>
                <div><dt>Code</dt><dd>{item.open_code ? "Open" : "Not linked"}</dd></div>
                <div><dt>Momentum</dt><dd>{item.momentum_direction ?? "Unknown"}</dd></div>
              </dl>
              <div className="card-actions">
                <Link to={`/research/${encodeURIComponent(item.id)}`}>Open research</Link>
                {item.papers[0] && (
                  <a href={`https://arxiv.org/abs/${item.papers[0].arxiv_id}`} rel="noreferrer" target="_blank">Paper ↗</a>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No research changes in the public snapshot</strong>
          <span>The existing research archive remains available during migration.</span>
        </div>
      )}
      <p className="data-timestamp">{items.length} operational techniques</p>
    </section>
  );
}
