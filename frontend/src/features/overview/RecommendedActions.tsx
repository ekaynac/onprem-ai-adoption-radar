import { Link } from "react-router-dom";

import type { CatalogItem } from "../releases/releaseQueries";


export function RecommendedActions({ items }: { items: CatalogItem[] }) {
  return (
    <section className="panel" aria-labelledby="actions-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Recommended actions</p>
          <h2 id="actions-title">Decisions ready for attention</h2>
        </div>
      </div>
      {items.length ? (
        <div className="action-list">
          {items.map((item) => {
            const recommendation =
              item.workspace_recommendation ?? item.public_recommendation;
            const ring = recommendation.ring ?? recommendation.public_ring;
            return (
              <article className="action-item" key={item.release_id}>
                <div>
                  <strong>
                    {ring === "adopt" ? "Adopt" : ring === "pilot" ? "Pilot" : "Review"}{" "}
                    {item.name}
                  </strong>
                  <p>
                    {(recommendation.reasons ?? [])[0] ??
                      "Evidence review complete."}
                  </p>
                </div>
                <Link to={`/compare?release=${encodeURIComponent(item.release_id)}`}>
                  Evaluate
                </Link>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="empty-state compact">
          <strong>No recommendation changes</strong>
          <span>Detected and verified releases remain intelligence, not advice.</span>
        </div>
      )}
    </section>
  );
}
