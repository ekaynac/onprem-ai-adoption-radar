import { Link } from "react-router-dom";

import { StatusBadge } from "../../design/StatusBadge";
import type { CatalogItem } from "./catalogQueries";


export function CatalogTable({ items }: { items: CatalogItem[] }) {
  if (!items.length) {
    return (
      <div className="empty-state">
        <strong>No catalog entities match this view</strong>
        <span>Try another category, lifecycle, or search term.</span>
      </div>
    );
  }

  return (
    <div className="catalog-table-wrap">
      <table className="catalog-table">
        <thead>
          <tr>
            <th>Model</th>
            <th>Category</th>
            <th>Lifecycle</th>
            <th>Lane</th>
            <th>Public posture</th>
            <th>Observed</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const ring = item.workspace_recommendation?.ring ??
              item.public_recommendation.ring;
            return (
              <tr key={item.release_id}>
                <td data-label="Model">
                  <Link to={`/catalog/${encodeURIComponent(item.release_id)}`}>
                    <strong>{item.name}</strong>
                    <span>{item.release_id}</span>
                  </Link>
                </td>
                <td data-label="Category">{item.category.replaceAll("_", " ")}</td>
                <td data-label="Lifecycle"><StatusBadge status={item.lifecycle} /></td>
                <td data-label="Lane">{item.lane.replaceAll("_", " ")}</td>
                <td data-label="Public posture">
                  {item.lane === "market_reference" ? "Reference only" : ring ?? "Unrated"}
                </td>
                <td data-label="Observed">
                  {new Date(item.first_observed_at).toLocaleDateString()}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
