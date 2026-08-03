import { Link } from "react-router-dom";

import type { OperationsHealth } from "../releases/releaseQueries";


export function CatalogTrust({ health }: { health?: OperationsHealth }) {
  const fresh = health?.fresh_claim_pct ??
    (health ? Math.max(0, 100 - health.stale_claim_count) : 0);
  const sources = health?.source_health ?? [];
  const healthySources =
    sources.filter(
      (source) =>
        ["ok", "empty"].includes(source.status ?? "") &&
        !source.circuit_open_until &&
        source.consecutive_failures === 0,
    ).length;
  const sourceCount = sources.length;

  return (
    <aside className="panel trust-panel" aria-labelledby="trust-title">
      <div>
        <p className="eyebrow">Catalog trust</p>
        <h2 id="trust-title">Evidence posture</h2>
      </div>
      <div className="trust-score">
        <strong>{fresh}%</strong>
        <span>claims within freshness policy</span>
      </div>
      <dl className="trust-facts">
        <div>
          <dt>Stale</dt>
          <dd>{health?.stale_claim_count ?? 0} stale claims</dd>
        </div>
        <div>
          <dt>Review</dt>
          <dd>{health?.open_review_count ?? 0} review exceptions</dd>
        </div>
        <div>
          <dt>Sources</dt>
          <dd>{healthySources}/{sourceCount} healthy</dd>
        </div>
      </dl>
      <Link to="/operations" className="text-link">Inspect operations →</Link>
    </aside>
  );
}
