import { Link } from "react-router-dom";

import type { Briefing } from "../catalog/catalogQueries";


const RING_ORDER = ["adopt", "pilot", "watch", "avoid"] as const;

function trendArrow(trend?: string | null): string | null {
  if (trend === "rising") return "↑";
  if (trend === "falling") return "↓";
  return null;
}

export function BriefingPanels({ briefing }: { briefing?: Briefing | null }) {
  if (!briefing) return null;
  const projects = briefing.rings.projects;
  const models = briefing.rings.models;
  const tracked = (projects.tracked ?? 0) + (models.tracked ?? 0);

  return (
    <>
      <section className="briefing-rings" aria-labelledby="ring-tiles-title">
        <h2 id="ring-tiles-title" className="visually-hidden">
          Ring distribution
        </h2>
        <div className="ring-tiles">
          <article className="ring-tile">
            <strong>{tracked}</strong>
            <span>Tracked</span>
          </article>
          {RING_ORDER.map((ring) => (
            <article className={`ring-tile tile-${ring}`} key={ring}>
              <strong>{(projects[ring] ?? 0) + (models[ring] ?? 0)}</strong>
              <span>{ring}</span>
            </article>
          ))}
        </div>
      </section>

      {briefing.try_this_week.length > 0 && (
        <section className="try-this-week" aria-labelledby="try-title">
          <div className="panel-heading">
            <h2 id="try-title">Try this week</h2>
            <Link to="/projects" className="text-link">
              All projects →
            </Link>
          </div>
          <div className="try-grid">
            {briefing.try_this_week.map((pick) => (
              <article className="try-card" key={pick.project}>
                <div className="try-card-head">
                  <Link
                    to={`/projects/${encodeURIComponent(pick.project)}`}
                    className="item-title"
                  >
                    {pick.project}
                  </Link>
                  <span className={`ring-pill pill-${pick.ring}`}>
                    {pick.ring}
                    {trendArrow(pick.trend) && (
                      <span aria-label={`trend ${pick.trend}`}>
                        {" "}
                        {trendArrow(pick.trend)}
                      </span>
                    )}
                  </span>
                </div>
                <p className="try-meta">
                  {pick.backer ? `${pick.backer} · ` : ""}
                  {(pick.category ?? "").replaceAll("_", " ")}
                  {pick.risk_level ? ` · ${pick.risk_level} risk` : ""}
                </p>
                {pick.note && <p className="try-note">{pick.note}</p>}
                {pick.evidence_notes.length > 0 && (
                  <ul className="try-evidence">
                    {pick.evidence_notes.map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                )}
              </article>
            ))}
          </div>
        </section>
      )}

      {briefing.movers.length > 0 && (
        <section className="movers" aria-labelledby="movers-title">
          <div className="panel-heading">
            <h2 id="movers-title">Movers</h2>
          </div>
          <ul className="mover-list">
            {briefing.movers.map((mover) => (
              <li key={`${mover.kind}:${mover.subject}:${mover.observed_at}`}>
                <Link
                  to={
                    mover.kind === "project"
                      ? `/projects/${encodeURIComponent(mover.subject)}`
                      : "/catalog"
                  }
                >
                  {mover.line}
                </Link>
                {mover.observed_at && (
                  <time dateTime={mover.observed_at}>
                    {new Date(mover.observed_at).toLocaleDateString()}
                  </time>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
