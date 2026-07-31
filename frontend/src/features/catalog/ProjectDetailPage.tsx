import { Link, useParams } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


function readable(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}


export function ProjectDetailPage() {
  const { projectName = "" } = useParams();
  const snapshot = usePublicSnapshot();
  const project = snapshot.data?.projects.find(
    (item) => item.project === projectName,
  );

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading project"><span /></div>;
  }
  if (!project) {
    return (
      <div className="empty-state">
        <strong>Project not found</strong>
        <Link to="/projects">Return to GitHub projects</Link>
      </div>
    );
  }

  const metrics = project.latest_metrics ?? {};
  return (
    <section className="page-stack" aria-labelledby="project-title">
      <Link className="text-link" to="/projects">← GitHub projects</Link>
      <header className="detail-hero">
        <div>
          <p className="eyebrow">{project.category.replaceAll("_", " ")}</p>
          <h1 id="project-title">{project.project}</h1>
          <p className="lede">{project.summary}</p>
        </div>
        <span className={`ring-pill ring-${project.ring}`}>{project.ring}</span>
      </header>
      <div className="detail-grid">
        <section className="panel">
          <p className="eyebrow">Architect decision</p>
          <h2>Why it matters</h2>
          <p className="body-copy">{project.why_it_matters || project.on_prem_fit}</p>
          <h3>On-prem fit</h3>
          <p className="body-copy">{project.on_prem_fit || "No fit note recorded."}</p>
          {project.what_changed.length > 0 && (
            <>
              <h3>What changed</h3>
              <ul className="detail-list">
                {project.what_changed.map((item) => <li key={item}>{item}</li>)}
              </ul>
            </>
          )}
        </section>
        <aside className="panel">
          <p className="eyebrow">Current posture</p>
          <dl className="detail-facts stacked">
            <div><dt>Score</dt><dd>{project.score.toFixed(2)}</dd></div>
            <div><dt>Risk</dt><dd>{project.risk_level}</dd></div>
            <div><dt>Trend</dt><dd>{project.trend}</dd></div>
            <div><dt>Backer</dt><dd>{project.backer?.name ?? "Community / unknown"}</dd></div>
            <div><dt>Reviewed</dt><dd>{new Date(project.last_reviewed_at).toLocaleString()}</dd></div>
          </dl>
          {project.repository_url && (
            <a className="primary-link inline-link" href={project.repository_url} rel="noreferrer" target="_blank">
              Open GitHub repository ↗
            </a>
          )}
        </aside>
      </div>
      <div className="detail-grid">
        <section className="panel">
          <p className="eyebrow">Validation</p>
          <h2>Try this week</h2>
          {project.try_this_week.length ? (
            <ol className="detail-list ordered">
              {project.try_this_week.map((item) => <li key={item}>{item}</li>)}
            </ol>
          ) : (
            <p className="body-copy">No validation action recorded.</p>
          )}
        </section>
        <section className="panel">
          <p className="eyebrow">Latest repository signals</p>
          <h2>Observed metrics</h2>
          <dl className="detail-facts stacked">
            <div><dt>Stars</dt><dd>{readable(metrics.stars)}</dd></div>
            <div><dt>Forks</dt><dd>{readable(metrics.forks)}</dd></div>
            <div><dt>Contributors</dt><dd>{readable(metrics.contributors)}</dd></div>
            <div><dt>Releases in window</dt><dd>{readable(metrics.releases_in_window)}</dd></div>
            <div><dt>HN mentions</dt><dd>{readable(metrics.hn_mentions)}</dd></div>
          </dl>
        </section>
      </div>
      <section className="panel">
        <p className="eyebrow">Evidence</p>
        <h2>Sources and observed notes</h2>
        <div className="evidence-links">
          {project.evidence.map((url) => (
            <a href={url} key={url} rel="noreferrer" target="_blank">{url}</a>
          ))}
        </div>
        {project.evidence_notes.length > 0 && (
          <ul className="detail-list">
            {project.evidence_notes.map((note) => <li key={note}>{note}</li>)}
          </ul>
        )}
      </section>
    </section>
  );
}
