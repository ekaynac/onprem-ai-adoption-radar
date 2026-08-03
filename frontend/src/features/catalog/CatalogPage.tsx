import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useActiveWorkspaceId } from "../releases/releaseQueries";
import { CatalogFilters } from "./CatalogFilters";
import { CatalogTable } from "./CatalogTable";
import {
  useCatalogSearch,
  useCatalogFacets,
  type CatalogSearch,
} from "./catalogQueries";


const filterNames: Array<keyof CatalogSearch> = [
  "category",
  "lifecycle",
  "lane",
  "publisher",
  "license",
  "hardware",
  "modality",
  "platform",
  "freshness",
];


export function CatalogPage() {
  const [params, setParams] = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [debouncedQuery, setDebouncedQuery] = useState(query);
  const workspaceId = useActiveWorkspaceId();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query), 300);
    return () => window.clearTimeout(timer);
  }, [query]);

  const filters = useMemo<CatalogSearch>(() => {
    const values = Object.fromEntries(
      filterNames.map((name) => [name, params.get(name) ?? "all"]),
    ) as Omit<CatalogSearch, "query">;
    return { query: debouncedQuery, ...values };
  }, [debouncedQuery, params]);
  const catalog = useCatalogSearch(filters, workspaceId);
  const facets = useCatalogFacets();
  const visible = (catalog.data?.items ?? []).filter(
    (item) => filters.lane === "all" || item.lane === filters.lane,
  );

  function update(name: keyof CatalogSearch, value: string) {
    if (name === "query") {
      setQuery(value);
      const next = new URLSearchParams(params);
      if (value) next.set("q", value);
      else next.delete("q");
      setParams(next, { replace: true });
      return;
    }
    const next = new URLSearchParams(params);
    if (value === "all") next.delete(name);
    else next.set(name, value);
    setParams(next, { replace: true });
  }

  return (
    <section className="page-stack" aria-labelledby="catalog-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Unified catalog</p>
          <h1 id="catalog-title">Models, evidence, and deployment posture</h1>
          <p className="lede">
            Six model categories in one provenance-first inventory. Every
            unknown stays explicit.
          </p>
        </div>
      </header>
      <CatalogFilters
        filters={{ ...filters, query }}
        facets={facets.data}
        onChange={update}
      />
      {catalog.isLoading ? (
        <div className="loading-grid" aria-label="Loading catalog"><span /><span /></div>
      ) : catalog.isError ? (
        <div className="error-state" role="alert">
          <strong>Catalog search unavailable</strong>
          <button type="button" onClick={() => void catalog.refetch()}>Try again</button>
        </div>
      ) : (
        <CatalogTable items={visible} />
      )}
      <p className="data-timestamp">
        {visible.length} entities · filters are preserved in the URL
      </p>
    </section>
  );
}
