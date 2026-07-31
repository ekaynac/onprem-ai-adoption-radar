import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


export function ProjectsPage() {
  const snapshot = usePublicSnapshot();
  const [query, setQuery] = useState("");
  const [ring, setRing] = useState("all");
  const projects = useMemo(
    () =>
      (snapshot.data?.projects ?? []).filter((project) => {
        const haystack =
          `${project.project} ${project.category} ${project.summary}`.toLowerCase();
        return (
          (!query || haystack.includes(query.toLowerCase())) &&
          (ring === "all" || project.ring === ring)
        );
      }),
    [query, ring, snapshot.data?.projects],
  );
  const isBaseline =
    snapshot.data?.project_data?.mode === "last_published_baseline";
  const baselineDate = snapshot.data?.project_data?.generated_at
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(new Date(snapshot.data.project_data.generated_at))
    : "an unknown date";

  return (
    <section className="page-stack" aria-labelledby="projects-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · GitHub projects</p>
          <h1 id="projects-title">The open-source systems behind on-prem AI</h1>
          <p className="lede">
            {isBaseline
              ? `Last published repository baseline from ${baselineDate}; the current scan projection was unavailable at export.`
              : "Live repository evidence, adoption posture, risk, and the next practical validation step."}
          </p>
        </div>
      </header>
      <div className="compact-filters">
        <label>
          <span>Search projects</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="vLLM, agents, serving…"
          />
        </label>
        <label>
          <span>Ring</span>
          <select value={ring} onChange={(event) => setRing(event.target.value)}>
            <option value="all">All rings</option>
            <option value="adopt">Adopt</option>
            <option value="pilot">Pilot</option>
            <option value="watch">Watch</option>
            <option value="avoid">Avoid</option>
          </select>
        </label>
      </div>
      {snapshot.isLoading ? (
        <div className="loading-grid" aria-label="Loading projects"><span /></div>
      ) : projects.length ? (
        <div className="entity-card-grid">
          {projects.map((project) => (
            <article className="panel intelligence-card" key={project.project}>
              <div className="card-topline">
                <span className={`ring-pill ring-${project.ring}`}>
                  {project.ring}
                </span>
                <span>{project.trend}</span>
              </div>
              <div>
                <p className="eyebrow">{project.category.replaceAll("_", " ")}</p>
                <h2>{project.project}</h2>
                <p className="card-summary">{project.summary}</p>
              </div>
              <dl className="mini-facts">
                <div><dt>Score</dt><dd>{project.score.toFixed(2)}</dd></div>
                <div><dt>Risk</dt><dd>{project.risk_level}</dd></div>
                <div><dt>Reviewed</dt><dd>{new Date(project.last_reviewed_at).toLocaleDateString()}</dd></div>
              </dl>
              <div className="card-actions">
                <Link to={`/projects/${encodeURIComponent(project.project)}`}>
                  Open intelligence
                </Link>
                {project.repository_url && (
                  <a href={project.repository_url} rel="noreferrer" target="_blank">
                    GitHub ↗
                  </a>
                )}
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No projects match this view</strong>
          <span>Clear a search or broaden the adoption ring.</span>
        </div>
      )}
      <p className="data-timestamp">
        {isBaseline
          ? `${projects.length} project decisions · last published baseline from ${baselineDate}`
          : `${projects.length} live project decisions`}
      </p>
    </section>
  );
}
