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

  // Union of canonical benchmarks across the selection (aggregates first,
  // legacy profile.benchmarks as fallback), ordered by how many of the
  // selected models report them (most comparable first).
  const benchmarkKeys = useMemo(() => {
    const counts = new Map<string, { label: string; count: number }>();
    for (const item of rows) {
      const aggregates = item.profile?.benchmark_aggregates;
      if (aggregates?.length) {
        for (const aggregate of aggregates) {
          const entry = counts.get(aggregate.benchmark) ?? {
            label: aggregate.label,
            count: 0,
          };
          entry.count += 1;
          counts.set(aggregate.benchmark, entry);
        }
        continue;
      }
      for (const benchmark of item.profile?.benchmarks ?? []) {
        const entry = counts.get(benchmark.name) ?? {
          label: benchmark.name,
          count: 0,
        };
        entry.count += 1;
        counts.set(benchmark.name, entry);
      }
    }
    return [...counts.entries()]
      .sort(
        (left, right) =>
          right[1].count - left[1].count || left[0].localeCompare(right[0]),
      )
      .map(([key, entry]) => ({ key, label: entry.label }));
  }, [rows]);

  function aggregateFor(item: CatalogItem, key: string) {
    const aggregate = (item.profile?.benchmark_aggregates ?? []).find(
      (row) => row.benchmark === key,
    );
    if (aggregate) return aggregate;
    const legacy = (item.profile?.benchmarks ?? []).find(
      (benchmark) => benchmark.name === key,
    );
    if (!legacy) return null;
    return {
      benchmark: key,
      label: legacy.name,
      consensus: legacy.score,
      spread: null,
      self_reported_gap: null,
      flagged: false,
      percentile: null,
      sample_size: 0,
      scores: [
        {
          source_id: "model-card",
          score: legacy.score,
          source_url: legacy.source_url,
          self_reported: true,
        },
      ],
    };
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
      {rows.length >= 2 && benchmarkKeys.length > 0 && (
        <section className="panel" aria-labelledby="benchmark-compare-title">
          <div className="panel-heading">
            <div>
              <p className="eyebrow">Triangulated benchmarks</p>
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
                {benchmarkKeys.map(({ key, label }) => {
                  const aggregates = rows.map((item) => aggregateFor(item, key));
                  const best = Math.max(
                    ...aggregates.map(
                      (aggregate) => aggregate?.consensus ?? -Infinity,
                    ),
                  );
                  return (
                    <tr key={key}>
                      <td>{label}</td>
                      {rows.map((item) => {
                        const aggregate = aggregateFor(item, key);
                        if (!aggregate || aggregate.consensus == null) {
                          return <td key={item.release_id}>—</td>;
                        }
                        const primary =
                          aggregate.scores.find(
                            (score) => !score.self_reported,
                          ) ?? aggregate.scores[0];
                        return (
                          <td
                            key={item.release_id}
                            className={
                              aggregate.consensus === best
                                ? "benchmark-best"
                                : undefined
                            }
                          >
                            <a
                              href={primary.source_url}
                              rel="noreferrer"
                              target="_blank"
                            >
                              {aggregate.consensus}
                            </a>
                            {aggregate.scores.length > 1 && (
                              <span className="benchmark-sources">
                                {" "}
                                · {aggregate.scores.length} src
                              </span>
                            )}
                            {aggregate.flagged && (
                              <span
                                className="benchmark-flag"
                                title={`Self-reported differs from independent by ${aggregate.self_reported_gap} points`}
                              >
                                {" "}
                                ⚠
                              </span>
                            )}
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
            Consensus is the median of independent sources; ⚠ marks a
            self-reported score that differs from independents beyond the
            threshold. Every score links to its source; missing stays
            missing.
          </p>
        </section>
      )}
    </section>
  );
}
