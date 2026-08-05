import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";
import type { HardwareRecord } from "./catalogQueries";


function HardwareCard({ item }: { item: HardwareRecord }) {
  return (
    <Link
      aria-label={`Open ${item.name} capacity record`}
      className="panel intelligence-card entity-link-card"
      to={`/hardware/${encodeURIComponent(item.id)}`}
    >
      <div className="card-topline">
        <span>{item.vendor ?? item.manufacturer ?? item.kind}</span>
        <span>{item.datacenter ? "Datacenter" : "Local"}</span>
      </div>
      <div>
        <p className="eyebrow">
          {item.vendor && item.chip
            ? `${item.gpu_count}× ${item.chip}`
            : `${item.gpu_count} accelerator(s)`}
        </p>
        <h2>{item.name}</h2>
      </div>
      <dl className="mini-facts">
        <div>
          <dt>Aggregate memory</dt>
          <dd>
            {item.aggregate_memory_gb ?? item.total_memory_gb * item.gpu_count}{" "}
            GB
          </dd>
        </div>
        <div>
          <dt>Bandwidth</dt>
          <dd>
            {item.memory_bandwidth_gbs
              ? `${item.memory_bandwidth_gbs} GB/s`
              : "Unknown"}
          </dd>
        </div>
        <div>
          <dt>Power</dt>
          <dd>{item.tdp_watts ? `${item.tdp_watts} W` : "Unknown"}</dd>
        </div>
      </dl>
      <span className="text-link">Open capacity record →</span>
    </Link>
  );
}


export function HardwarePage() {
  const snapshot = usePublicSnapshot();
  const [query, setQuery] = useState("");
  const [maker, setMaker] = useState("all");

  const hardware = useMemo(
    () => snapshot.data?.hardware ?? [],
    [snapshot.data?.hardware],
  );
  const makers = useMemo(
    () =>
      [
        ...new Set(
          hardware
            .map((item) => item.vendor ?? item.manufacturer)
            .filter((value): value is string => Boolean(value)),
        ),
      ].sort(),
    [hardware],
  );
  const items = useMemo(
    () =>
      hardware.filter(
        (item) =>
          (!query ||
            `${item.name} ${item.id} ${item.chip ?? ""}`
              .toLowerCase()
              .includes(query.toLowerCase())) &&
          (maker === "all" ||
            item.vendor === maker ||
            item.manufacturer === maker),
      ),
    [hardware, maker, query],
  );
  // Taxonomy: vendor systems (a builder + contained chips) vs the chips
  // and reference boards they contain.
  const systems = items.filter((item) => item.vendor);
  const chips = items.filter((item) => !item.vendor);

  return (
    <section className="page-stack" aria-labelledby="hardware-page-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Evidence · Hardware</p>
          <h1 id="hardware-page-title">Infrastructure capacity catalog</h1>
          <p className="lede">
            Vendor systems classified by the chips inside them, plus the
            chips themselves — every spec cites its source.
          </p>
        </div>
      </header>
      <div className="compact-filters">
        <label>
          <span>Search hardware</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="DGX Spark, H200, MI300X…"
          />
        </label>
        <label>
          <span>Manufacturer</span>
          <select value={maker} onChange={(event) => setMaker(event.target.value)}>
            <option value="all">All manufacturers</option>
            {makers.map((value) => (
              <option value={value} key={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>
      {snapshot.isLoading ? (
        <div className="loading-grid" aria-label="Loading hardware">
          <span />
        </div>
      ) : items.length ? (
        <>
          {systems.length > 0 && (
            <section aria-labelledby="hardware-systems-title">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Systems</p>
                  <h2 id="hardware-systems-title">
                    Platforms you can buy and rack
                  </h2>
                </div>
              </div>
              <div className="entity-card-grid">
                {systems.map((item) => (
                  <HardwareCard item={item} key={item.id} />
                ))}
              </div>
            </section>
          )}
          {chips.length > 0 && (
            <section aria-labelledby="hardware-chips-title">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">Chips & reference boards</p>
                  <h2 id="hardware-chips-title">What the systems contain</h2>
                </div>
              </div>
              <div className="entity-card-grid">
                {chips.map((item) => (
                  <HardwareCard item={item} key={item.id} />
                ))}
              </div>
            </section>
          )}
        </>
      ) : (
        <div className="empty-state">
          <strong>No hardware matches this view</strong>
          <span>Clear the search or manufacturer filter.</span>
        </div>
      )}
      <p className="data-timestamp">
        {systems.length} system(s) · {chips.length} chip(s)/board(s)
      </p>
    </section>
  );
}
