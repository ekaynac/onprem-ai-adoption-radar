import { useMemo, useState } from "react";

import { StatusBadge } from "../../design/StatusBadge";
import { useActiveWorkspaceId } from "../workspaces/workspaceStore";
import {
  useCatalogSearch,
  type CatalogItem,
  type CatalogSearch,
} from "../catalog/catalogQueries";
import { formatContext, formatParams } from "../catalog/format";


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
};


export function ComparePage() {
  const workspaceId = useActiveWorkspaceId();
  const [selected, setSelected] = useState<Record<string, CatalogItem>>({});
  const [query, setQuery] = useState("");
  const catalogFilters = { ...filters, query };
  const catalog = useCatalogSearch(catalogFilters, workspaceId);
  const rows = Object.values(selected);

  // Union of benchmark names across the selection, ordered by how many of
  // the selected models report them (most comparable first).
  const benchmarkNames = useMemo(() => {
    const counts = new Map<string, number>();
    for (const item of rows) {
      for (const benchmark of item.profile?.benchmarks ?? []) {
        counts.set(benchmark.name, (counts.get(benchmark.name) ?? 0) + 1);
      }
    }
    return [...counts.entries()]
      .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
      .map(([name]) => name);
  }, [rows]);

  function benchmarkFor(item: CatalogItem, name: string) {
    return (item.profile?.benchmarks ?? []).find(
      (benchmark) => benchmark.name === name,
    );
  }

  function toggle(item: CatalogItem) {
    setSelected((current) => {
      if (current[item.release_id]) {
        const next = { ...current };
        delete next[item.release_id];
        return next;
      }
      return Object.keys(current).length < 6
        ? { ...current, [item.release_id]: item }
        : current;
    });
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
      <label className="catalog-search">
        <span>Find models to compare</span>
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search the complete model index…"
        />
      </label>
      <div className="compare-picker">
        {(catalog.data?.items ?? []).slice(0, 50).map((item) => (
          <label key={item.release_id}>
            <input
              type="checkbox"
              checked={Boolean(selected[item.release_id])}
              disabled={!selected[item.release_id] && rows.length >= 6}
              onChange={() => toggle(item)}
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
                <div><dt>Ring</dt><dd>{item.public_recommendation.ring ?? "Unrated"}</dd></div>
                <div>
                  <dt>Params</dt>
                  <dd>
                    {formatParams(
                      item.profile?.params_total,
                      item.profile?.params_active,
                    ) ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>Context</dt>
                  <dd>{formatContext(item.profile?.context_length) ?? "—"}</dd>
                </div>
                <div><dt>License</dt><dd>{item.profile?.license ?? "—"}</dd></div>
                <div>
                  <dt>Tier</dt>
                  <dd>{item.profile?.hardware_tier ?? "—"}</dd>
                </div>
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
      {rows.length >= 2 && benchmarkNames.length > 0 && (
        <section className="panel" aria-labelledby="benchmark-compare-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Curated benchmarks</p>
              <h2 id="benchmark-compare-title">Score comparison</h2>
            </div>
          </div>
          <div className="release-table-wrap">
            <table className="release-table benchmark-table">
              <thead>
                <tr>
                  <th>Benchmark</th>
                  {rows.map((item) => (
                    <th key={item.release_id}>{item.name}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {benchmarkNames.map((name) => {
                  const scores = rows.map((item) => benchmarkFor(item, name));
                  const best = Math.max(
                    ...scores.map((score) => score?.score ?? -Infinity),
                  );
                  return (
                    <tr key={name}>
                      <td>{name}</td>
                      {rows.map((item) => {
                        const benchmark = benchmarkFor(item, name);
                        if (!benchmark) {
                          return <td key={item.release_id}>—</td>;
                        }
                        return (
                          <td
                            key={item.release_id}
                            className={
                              benchmark.score === best
                                ? "benchmark-best"
                                : undefined
                            }
                          >
                            <a
                              href={benchmark.source_url}
                              rel="noreferrer"
                              target="_blank"
                            >
                              {benchmark.score}
                            </a>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="claim-meta">
            Every score links to its source. Missing scores stay missing —
            models report different suites.
          </p>
        </section>
      )}
    </section>
  );
}
