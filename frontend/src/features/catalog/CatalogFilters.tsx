import type { CatalogSearch } from "./catalogQueries";


type Props = {
  filters: CatalogSearch;
  onChange: (name: keyof CatalogSearch, value: string) => void;
};


export function CatalogFilters({ filters, onChange }: Props) {
  return (
    <div className="catalog-filters" aria-label="Catalog filters">
      <label className="catalog-search">
        <span>Search intelligence</span>
        <input
          value={filters.query}
          onChange={(event) => onChange("query", event.target.value)}
          placeholder="Model, publisher, capability…"
          type="search"
        />
      </label>
      <label>
        <span>Model category</span>
        <select
          value={filters.category}
          onChange={(event) => onChange("category", event.target.value)}
        >
          <option value="all">All categories</option>
          <option value="text_reasoning">Text & reasoning</option>
          <option value="multimodal">Multimodal</option>
          <option value="embedding_reranking">Embedding & reranking</option>
          <option value="speech_audio">Speech & audio</option>
          <option value="image_video">Image & video</option>
          <option value="vision_document">Vision & documents</option>
        </select>
      </label>
      <label>
        <span>Lifecycle</span>
        <select
          value={filters.lifecycle}
          onChange={(event) => onChange("lifecycle", event.target.value)}
        >
          <option value="all">All states</option>
          <option value="detected">Detected</option>
          <option value="verified">Verified</option>
          <option value="qualified">Qualified</option>
          <option value="recommended">Recommended</option>
        </select>
      </label>
      <label>
        <span>Lane</span>
        <select value={filters.lane} onChange={(event) => onChange("lane", event.target.value)}>
          <option value="all">All lanes</option>
          <option value="deployable_onprem">Deployable on-prem</option>
          <option value="onprem_adjacent">On-prem adjacent</option>
          <option value="market_reference">Market reference</option>
        </select>
      </label>
      {[
        ["publisher", "Publisher"],
        ["license", "License"],
        ["hardware", "Hardware fit"],
        ["modality", "Modality"],
        ["platform", "Platform"],
        ["freshness", "Freshness"],
        ["review", "Review status"],
      ].map(([name, label]) => (
        <label key={name}>
          <span>{label}</span>
          <select
            value={filters[name as keyof CatalogSearch]}
            onChange={(event) =>
              onChange(name as keyof CatalogSearch, event.target.value)
            }
          >
            <option value="all">Any</option>
            {name === "freshness" && <option value="fresh">Fresh</option>}
            {name === "freshness" && <option value="stale">Stale</option>}
            {name === "review" && <option value="open">Exception open</option>}
          </select>
        </label>
      ))}
    </div>
  );
}
