import { Link } from "react-router-dom";

import { StatusBadge, type IntelligenceStatus } from "../../design/StatusBadge";
import { releaseAgeHours, type ReleaseChange } from "../releases/releaseQueries";


function ageLabel(hours: number) {
  if (hours < 1) {
    return `${Math.max(1, Math.round(hours * 60))}m ago`;
  }
  if (hours < 48) {
    return `${Math.round(hours)}h ago`;
  }
  return `${Math.round(hours / 24)}d ago`;
}


export function PriorityIntelligence({ items }: { items: ReleaseChange[] }) {
  if (!items.length) {
    return (
      <div className="empty-state">
        <strong>No new intelligence in this window</strong>
        <span>The source mesh is active and will surface the next verified change.</span>
      </div>
    );
  }

  return (
    <section className="panel priority-panel" aria-labelledby="priority-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Priority intelligence</p>
          <h2 id="priority-title">New signals that may change a decision</h2>
        </div>
        <Link to="/releases" className="text-link">Open release stream →</Link>
      </div>
      <div className="priority-list">
        {items.slice(0, 5).map((item) => (
          <article className="priority-item" key={item.release_id}>
            <div className="priority-main">
              <StatusBadge
                status={item.lifecycle as IntelligenceStatus}
              />
              <div>
                <Link
                  to={`/releases/${encodeURIComponent(item.release_id)}`}
                  className="item-title"
                >
                  {item.name}
                </Link>
                <p>
                  {item.category.replaceAll("_", " ")} ·{" "}
                  {item.lane.replaceAll("_", " ")}
                </p>
              </div>
            </div>
            <div className="signal-metrics">
              <span>{Math.round(item.confidence * 100)}% confidence</span>
              <time dateTime={item.released_at ?? item.first_observed_at}>
                {ageLabel(releaseAgeHours(item))}
              </time>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
