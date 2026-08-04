import { useMemo, useState } from "react";

import { usePublicSnapshot } from "../catalog/catalogQueries";


const IMPACT_LABELS: Record<string, string> = {
  breaking: "Breaking",
  improvement: "Improvement",
  informational: "Informational",
};

const VIEW_LABELS: Record<string, string> = {
  classified: "Classified only",
  breaking: "Breaking",
  improvement: "Improvements",
  informational: "Informational",
  all: "Everything (raw firehose)",
};


export function NewsroomPage() {
  const snapshot = usePublicSnapshot(true);
  const newsroom = snapshot.data?.newsroom ?? null;
  const [view, setView] = useState("classified");

  const rows = useMemo(() => {
    const items = newsroom?.items ?? [];
    if (view === "all") return items;
    if (view === "classified") {
      return items.filter((item) => item.classification != null);
    }
    return items.filter(
      (item) => item.classification?.operational_impact === view,
    );
  }, [newsroom?.items, view]);

  if (snapshot.isLoading) {
    return (
      <div className="loading-grid" aria-label="Loading newsroom">
        <span />
        <span />
      </div>
    );
  }

  return (
    <section className="page-stack" aria-labelledby="newsroom-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Newsroom</p>
          <h1 id="newsroom-title">Change intelligence, not headlines</h1>
          <p className="lede">
            Every article is classified for on-prem operators: what changed,
            which components it touches, and whether you must act. Items that
            fail classification stay in the raw firehose — never presented as
            intelligence.
          </p>
        </div>
        {newsroom && (
          <div className="freshness-stamp" aria-label="Newsroom counts">
            {newsroom.counts.classified} classified ·{" "}
            {newsroom.counts.breaking} breaking ·{" "}
            {newsroom.counts.unclassified} raw
          </div>
        )}
      </header>

      <div className="filter-bar" aria-label="Newsroom filters">
        <label>
          <span>View</span>
          <select
            value={view}
            onChange={(event) => setView(event.target.value)}
          >
            {Object.entries(VIEW_LABELS).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!newsroom || rows.length === 0 ? (
        <div className="empty-state">
          <strong>Nothing in this view yet</strong>
          <span>
            The newsroom fills as the 2-hourly sweep observes and classifies
            new articles.
          </span>
        </div>
      ) : (
        <ul className="brief-list">
          {rows.map((item) => {
            const classification = item.classification ?? null;
            return (
              <li key={item.id}>
                <div className="brief-item-head">
                  <strong>
                    <a href={item.url} rel="noreferrer" target="_blank">
                      {item.title}
                    </a>
                  </strong>
                  {classification ? (
                    <span
                      className={`verdict-pill impact-${classification.operational_impact}`}
                    >
                      {IMPACT_LABELS[classification.operational_impact]}
                    </span>
                  ) : (
                    <span className="verdict-pill impact-unclassified">
                      Unclassified
                    </span>
                  )}
                </div>
                {classification ? (
                  <>
                    <p>{classification.summary}</p>
                    <p className="claim-meta">
                      <span className="lineage-chip">
                        {classification.event_type}
                      </span>
                      {classification.components.map((component) => (
                        <span className="lineage-chip" key={component}>
                          {component}
                        </span>
                      ))}
                    </p>
                  </>
                ) : (
                  item.summary && <p className="claim-reason">{item.summary}</p>
                )}
                <p className="claim-meta">
                  {item.source_id}
                  {item.published_at &&
                    ` · ${new Date(item.published_at).toLocaleDateString()}`}
                  {classification && ` · classified by ${classification.model}`}
                </p>
              </li>
            );
          })}
        </ul>
      )}
      <p className="data-timestamp">
        {rows.length} item(s) in view · {newsroom?.counts.total ?? 0} observed
      </p>
    </section>
  );
}
