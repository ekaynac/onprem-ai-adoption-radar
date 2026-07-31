import { useState } from "react";

import { StatusBadge } from "../../design/StatusBadge";
import { useActiveWorkspaceId } from "../workspaces/workspaceStore";
import { useCatalogSearch, type CatalogSearch } from "../catalog/catalogQueries";


const filters: CatalogSearch = {
  query: "",
  category: "all",
  lifecycle: "all",
  lane: "all",
  publisher: "all",
  license: "all",
  hardware: "all",
  modality: "all",
  platform: "all",
  freshness: "all",
  review: "all",
};


export function ComparePage() {
  const workspaceId = useActiveWorkspaceId();
  const catalog = useCatalogSearch(filters, workspaceId);
  const [selected, setSelected] = useState<string[]>([]);
  const rows = (catalog.data?.items ?? []).filter((item) =>
    selected.includes(item.release_id),
  );

  function toggle(id: string) {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((value) => value !== id)
        : current.length < 6
          ? [...current, id]
          : current,
    );
  }

  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Decide · Compare</p>
          <h1>Pin the differences that change architecture</h1>
          <p className="lede">Select two to six candidates. Public and workspace verdicts stay separate.</p>
        </div>
      </header>
      <div className="compare-picker">
        {(catalog.data?.items ?? []).slice(0, 20).map((item) => (
          <label key={item.release_id}>
            <input
              type="checkbox"
              checked={selected.includes(item.release_id)}
              disabled={!selected.includes(item.release_id) && selected.length >= 6}
              onChange={() => toggle(item.release_id)}
            />
            {item.name}
          </label>
        ))}
      </div>
      {rows.length >= 2 ? (
        <div className="compare-grid" style={{ "--compare-count": rows.length } as React.CSSProperties}>
          {rows.map((item) => (
            <article className="panel" key={item.release_id}>
              <h2>{item.name}</h2>
              <StatusBadge status={item.lifecycle} />
              <dl className="detail-facts">
                <div><dt>Category</dt><dd>{item.category}</dd></div>
                <div><dt>Lane</dt><dd>{item.lane}</dd></div>
                <div><dt>Public</dt><dd>{item.public_recommendation.ring ?? "Unrated"}</dd></div>
                <div>
                  <dt>Workspace</dt>
                  <dd>{item.workspace_recommendation?.ring ?? "Same as public"}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>Select at least two candidates</strong>
          <span>Differing fields will be pinned side by side.</span>
        </div>
      )}
    </section>
  );
}
