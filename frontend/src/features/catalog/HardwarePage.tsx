import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


export function HardwarePage() {
  const snapshot = usePublicSnapshot();
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("all");
  const items = useMemo(
    () =>
      (snapshot.data?.hardware ?? []).filter(
        (item) =>
          (!query ||
            `${item.name} ${item.id}`.toLowerCase().includes(query.toLowerCase())) &&
          (kind === "all" || item.kind === kind),
      ),
    [kind, query, snapshot.data?.hardware],
  );
  return (
    <section className="page-stack" aria-labelledby="hardware-page-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Intelligence · Hardware</p>
          <h1 id="hardware-page-title">Infrastructure capacity catalog</h1>
          <p className="lede">Accelerators, memory topology, and deployment-fit evidence.</p>
        </div>
      </header>
      <div className="compact-filters">
        <label>
          <span>Search hardware</span>
          <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="H200, MI300X, Apple…" />
        </label>
        <label>
          <span>Topology</span>
          <select value={kind} onChange={(event) => setKind(event.target.value)}>
            <option value="all">All topologies</option>
            <option value="gpu">GPU</option>
            <option value="apple">Apple</option>
            <option value="cpu">CPU</option>
            <option value="node">Node</option>
            <option value="cluster">Cluster</option>
          </select>
        </label>
      </div>
      {snapshot.isLoading ? (
        <div className="loading-grid" aria-label="Loading hardware"><span /></div>
      ) : items.length ? (
        <div className="entity-card-grid">
          {items.map((item) => (
            <Link
              aria-label={`Open ${item.name} capacity record`}
              className="panel intelligence-card entity-link-card"
              key={item.id}
              to={`/hardware/${encodeURIComponent(item.id)}`}
            >
              <div className="card-topline"><span>{item.kind}</span><span>{item.datacenter ? "Datacenter" : "Local"}</span></div>
              <div>
                <p className="eyebrow">{item.gpu_count} accelerator(s)</p>
                <h2>{item.name}</h2>
              </div>
              <dl className="mini-facts">
                <div><dt>Aggregate memory</dt><dd>{item.aggregate_memory_gb ?? item.total_memory_gb * item.gpu_count} GB</dd></div>
                <div><dt>Bandwidth</dt><dd>{item.memory_bandwidth_gbs ? `${item.memory_bandwidth_gbs} GB/s` : "Unknown"}</dd></div>
                <div><dt>Power</dt><dd>{item.tdp_watts ? `${item.tdp_watts} W` : "Unknown"}</dd></div>
              </dl>
              <span className="text-link">Open capacity record →</span>
            </Link>
          ))}
        </div>
      ) : (
        <div className="empty-state">
          <strong>No canonical hardware observations yet</strong>
          <span>Add a workspace device or ingest a verified hardware registry.</span>
        </div>
      )}
      <p className="data-timestamp">{items.length} hardware topologies</p>
    </section>
  );
}
