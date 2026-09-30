import { useMemo, useState } from "react";

import { type PulseLane, type PulseRow, usePulse } from "./pulseQueries";


const PERIODS: Record<string, { label: string; hours: number | null }> = {
  day: { label: "Last 24 hours", hours: 24 },
  week: { label: "Last 7 days", hours: 24 * 7 },
  all: { label: "Everything in the window", hours: null },
};
/** First screen per lane; "Show all" reveals every item (the owner wants all). */
const INITIAL_PER_LANE = 15;
const FEEDS: Record<string, string> = {
  model: "pulse-models.xml",
  paper: "pulse-papers.xml",
  repo: "pulse-repos.xml",
  news: "pulse-news.xml",
};


function withinPeriod(row: PulseRow, hours: number | null, now: number): boolean {
  if (hours === null) return true;
  return now - Date.parse(row.first_seen) <= hours * 3_600_000;
}


export function PulsePage() {
  const pulse = usePulse();
  const [period, setPeriod] = useState("week");
  const view = pulse.data ?? null;
  const now = useMemo(
    () => (view ? Date.parse(view.generated_at) : Date.now()),
    [view],
  );

  if (pulse.isLoading) {
    return (
      <div className="loading-grid" aria-label="Loading pulse">
        <span />
        <span />
      </div>
    );
  }
  if (pulse.isError || !view) {
    return (
      <div className="empty-state" role="alert">
        <strong>Pulse is unavailable right now</strong>
        <span>The latest publish did not ship Pulse data. The source health page has details.</span>
      </div>
    );
  }

  const hours = PERIODS[period].hours;
  const failing = view.health.sources.filter((source) => source.status !== "ok");

  return (
    <section className="page-stack" aria-labelledby="pulse-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Pulse · what's new</p>
          <h1 id="pulse-title">New models, papers, repositories and news</h1>
          <p className="lede">
            Collected every two hours from Hugging Face, arXiv daily papers,
            GitHub and lab blogs. The classifier (Jev) says what each item
            is; readable rules rank it; every position shows why.
          </p>
        </div>
        <div className="freshness-stamp" aria-label="Pulse freshness">
          Updated {new Date(view.generated_at).toLocaleString("en-US")} ·{" "}
          <a href="pulse.xml">RSS</a>
        </div>
      </header>

      {(view.health.degraded || failing.length > 0) && (
        <div className="empty-state compact" role="status">
          {view.health.degraded && (
            <strong>Triage degraded: most items were ranked by fallback rules, not Jev.</strong>
          )}
          {failing.map((source) => (
            <span key={source.source}>
              {source.source}: {source.status} ({source.count} items)
            </span>
          ))}
        </div>
      )}

      <div className="filter-bar" aria-label="Pulse filters">
        <label>
          <span>Period</span>
          <select value={period} onChange={(event) => setPeriod(event.target.value)}>
            {Object.entries(PERIODS).map(([value, option]) => (
              <option value={value} key={value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {view.lanes.map((lane) => (
        <LaneSection key={lane.lane} lane={lane} hours={hours} now={now} />
      ))}
    </section>
  );
}


function LaneSection({ lane, hours, now }: { lane: PulseLane; hours: number | null; now: number }) {
  const [expanded, setExpanded] = useState(false);
  const inPeriod = lane.items.filter((row) => withinPeriod(row, hours, now));
  const rows = expanded ? inPeriod : inPeriod.slice(0, INITIAL_PER_LANE);
  const uncertain = lane.uncertain.filter((row) => withinPeriod(row, hours, now));
  const hidden = lane.hidden.filter((row) => withinPeriod(row, hours, now));
  const headingId = `pulse-lane-${lane.lane}`;
  return (
    <section aria-labelledby={headingId} className="page-stack">
      <div className="brief-item-head">
        <h2 id={headingId}>
          {lane.title} <span className="claim-meta">({inPeriod.length})</span>
        </h2>
        <span className="claim-meta">
          {lane.total} seen · {lane.hidden_count} filtered out ·{" "}
          <a href={FEEDS[lane.lane]}>RSS</a>
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="empty-state compact">
          <strong>Nothing new in this period</strong>
        </div>
      ) : (
        <ol className="brief-list">
          {rows.map((row) => (
            <PulseItem key={row.id} row={row} />
          ))}
        </ol>
      )}
      {inPeriod.length > INITIAL_PER_LANE && (
        <button type="button" onClick={() => setExpanded((value) => !value)}>
          {expanded ? "Show fewer" : `Show all ${inPeriod.length}`}
        </button>
      )}
      {uncertain.length > 0 && (
        <details>
          <summary>{uncertain.length} item(s) the classifier was unsure about</summary>
          <ul className="brief-list">
            {uncertain.map((row) => (
              <PulseItem key={row.id} row={row} />
            ))}
          </ul>
        </details>
      )}
      {hidden.length > 0 && (
        <details>
          <summary>{hidden.length} item(s) filtered out, with the reason for each</summary>
          <ul className="brief-list">
            {hidden.map((row) => (
              <PulseItem key={row.id} row={row} />
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}


function PulseItem({ row }: { row: PulseRow }) {
  return (
    <li>
      <div className="brief-item-head">
        <strong>
          <a href={row.url} rel="noreferrer" target="_blank">
            {row.title}
          </a>
        </strong>
        <span
          className={`verdict-pill ${row.engine === "jev" ? "impact-improvement" : "impact-unclassified"}`}
          title={row.engine === "jev" ? "Triaged by Jev" : "Ranked by fallback rules"}
        >
          {row.engine ?? "untriaged"}
        </span>
      </div>
      {row.summary && <p>{row.summary}</p>}
      <p className="claim-meta">
        <span className="lineage-chip">{row.source}</span>{" "}
        {row.reasons.join(" · ")}
      </p>
    </li>
  );
}
