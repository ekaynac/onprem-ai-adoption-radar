import { Link } from "react-router-dom";

import { StatusBadge } from "../../design/StatusBadge";
import {
  derivativeCountsLabel,
  releaseLineage,
} from "../releases/releaseQueries";
import type { CatalogItem } from "./catalogQueries";
import { formatContext, formatParams } from "./format";


const UNKNOWN = "—";

export function CatalogTable({ items }: { items: CatalogItem[] }) {
  if (!items.length) {
    return (
      <div className="empty-state">
        <strong>No catalog entities match this view</strong>
        <span>Try another category, lifecycle, view, or search term.</span>
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
            <th>Ring</th>
            <th>Tier</th>
            <th>Params</th>
            <th>Context</th>
            <th>License</th>
            <th>Observed</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const ring = item.workspace_recommendation?.ring ??
              item.public_recommendation.ring;
            const lineage = releaseLineage(item);
            const variants = derivativeCountsLabel(lineage?.derivative_counts);
            const profile = item.profile ?? null;
            return (
              <tr key={item.release_id}>
                <td data-label="Model">
                  <Link to={`/catalog/${encodeURIComponent(item.release_id)}`}>
                    <strong>{item.name}</strong>
                    <span>{profile?.family ?? item.release_id}</span>
                  </Link>
                  {lineage?.relation && lineage.base_release && (
                    <span className="lineage-chip">
                      {lineage.relation.replaceAll("_", " ")} of{" "}
                      <Link
                        to={`/catalog/${encodeURIComponent(lineage.base_release)}`}
                      >
                        {lineage.base_release.split(":").slice(-2).join(" ")}
                      </Link>
                    </span>
                  )}
                  {!lineage?.relation && variants && (
                    <span className="lineage-chip">{variants}</span>
                  )}
                </td>
                <td data-label="Category">{item.category.replaceAll("_", " ")}</td>
                <td data-label="Lifecycle"><StatusBadge status={item.lifecycle} /></td>
                <td data-label="Ring">
                  {item.lane === "market_reference"
                    ? "Reference only"
                    : ring ?? "Unrated"}
                </td>
                <td data-label="Tier">
                  {profile?.hardware_tier && profile.hardware_tier !== "unknown"
                    ? profile.hardware_tier
                    : UNKNOWN}
                </td>
                <td data-label="Params">
                  {formatParams(profile?.params_total, profile?.params_active) ??
                    UNKNOWN}
                </td>
                <td data-label="Context">
                  {formatContext(profile?.context_length) ?? UNKNOWN}
                </td>
                <td data-label="License">{profile?.license ?? UNKNOWN}</td>
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
