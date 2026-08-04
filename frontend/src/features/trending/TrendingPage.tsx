import { useMemo, useState } from "react";

import { usePublicSnapshot } from "../catalog/catalogQueries";
import { formatCount } from "../catalog/format";


const WINDOW_LABELS: Record<string, string> = {
  "7d": "7 days",
  "30d": "30 days",
  "90d": "90 days",
};

const LANE_LABELS: Record<string, string> = {
  all: "All lanes",
  onprem: "On-prem",
  broader: "Broader AI",
};


function StarSparkline({
  points,
  label,
}: {
  points: Array<{ stars: number }>;
  label: string;
}) {
  if (points.length < 2) return <span aria-hidden="true">—</span>;
  const values = points.map((point) => point.stars);
  const minimum = Math.min(...values);
  const spread = Math.max(...values) - minimum || 1;
  const width = 120;
  const height = 28;
  const coordinates = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width;
      const y = height - ((value - minimum) / spread) * (height - 4) - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      role="img"
      aria-label={label}
    >
      <polyline
        points={coordinates}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}


export function TrendingPage() {
  const snapshot = usePublicSnapshot(true);
  const trending = snapshot.data?.trending ?? null;
  const [window, setWindow] = useState("7d");
  const [lane, setLane] = useState("all");

  const rows = useMemo(
    () =>
      (trending?.windows[window] ?? []).filter(
        (row) => lane === "all" || row.lane === lane,
      ),
    [trending?.windows, window, lane],
  );

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading trending"><span /><span /></div>;
  }

  return (
    <section className="page-stack" aria-labelledby="trending-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Trending repositories</p>
          <h1 id="trending-title">Star velocity across the ecosystem</h1>
          <p className="lede">
            Growth measured from our own repeated observations — stars per
            day over the selected window, never a single-snapshot rank.
          </p>
        </div>
      </header>
      <div className="filter-bar" aria-label="Trending filters">
        <label>
          <span>Window</span>
          <select
            value={window}
            onChange={(event) => setWindow(event.target.value)}
          >
            {Object.keys(trending?.windows ?? WINDOW_LABELS).map((key) => (
              <option value={key} key={key}>
                {WINDOW_LABELS[key] ?? key}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>Lane</span>
          <select value={lane} onChange={(event) => setLane(event.target.value)}>
            {Object.entries(LANE_LABELS).map(([value, label]) => (
              <option value={value} key={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!trending || !rows.length ? (
        <div className="empty-state">
          <strong>No trending observations for this view</strong>
          <span>Velocity needs at least two scans inside the window.</span>
        </div>
      ) : (
        <div className="release-table-wrap">
          <table className="release-table trending-table">
            <thead>
              <tr>
                <th>Repository</th>
                <th>Stars</th>
                <th>Stars/day</th>
                <th>Last {trending.sparkline_days} days</th>
                <th>First seen</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.repo}>
                  <td>
                    <a href={row.url} rel="noreferrer" target="_blank">
                      <strong>
                        {row.repo}
                        {row.is_new && (
                          <span className="new-badge">NEW</span>
                        )}
                      </strong>
                      {row.description && <span>{row.description}</span>}
                    </a>
                    {(row.topics ?? []).length > 0 && (
                      <span className="topic-row">
                        {(row.topics ?? []).map((topic) => (
                          <span className="lineage-chip" key={topic}>
                            {topic}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td>{formatCount(row.stars)}</td>
                  <td>
                    {row.velocity_per_day != null
                      ? `+${row.velocity_per_day}`
                      : "—"}
                  </td>
                  <td>
                    <StarSparkline
                      points={trending.series[row.repo] ?? []}
                      label={`${row.repo} star history`}
                    />
                  </td>
                  <td>{new Date(row.first_seen).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="data-timestamp">
        {rows.length} repositories · sorted by star velocity in the selected
        window
      </p>
    </section>
  );
}
