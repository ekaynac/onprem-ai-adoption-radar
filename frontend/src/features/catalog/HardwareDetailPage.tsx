import { Link, useParams } from "react-router-dom";

import { usePublicSnapshot } from "./catalogQueries";


function spec(value: string | number | null | undefined, suffix = "") {
  return value === null || value === undefined ? "Unknown" : `${value}${suffix}`;
}


export function HardwareDetailPage() {
  const { hardwareId = "" } = useParams();
  const snapshot = usePublicSnapshot();
  const hardware = snapshot.data?.hardware.find((item) => item.id === hardwareId);

  if (snapshot.isLoading) {
    return <div className="loading-grid" aria-label="Loading hardware"><span /></div>;
  }
  if (!hardware) {
    return <div className="empty-state"><strong>Hardware not found</strong><Link to="/hardware">Return to hardware</Link></div>;
  }
  return (
    <section className="page-stack" aria-labelledby="hardware-title">
      <Link className="text-link" to="/hardware">← Hardware</Link>
      <header className="detail-hero">
        <div>
          <p className="eyebrow">{hardware.kind} · {hardware.datacenter ? "Datacenter" : "Local"}</p>
          <h1 id="hardware-title">{hardware.name}</h1>
          <p className="lede">{hardware.gpu_count} accelerator(s) · {hardware.aggregate_memory_gb ?? hardware.total_memory_gb * hardware.gpu_count} GB aggregate memory</p>
        </div>
      </header>
      <section className="panel">
        <p className="eyebrow">Capacity facts</p>
        <h2>Infrastructure specification</h2>
        <dl className="spec-grid">
          <div><dt>Accelerators</dt><dd>{hardware.gpu_count}</dd></div>
          <div><dt>Per accelerator</dt><dd>{spec(hardware.total_memory_gb, " GB")}</dd></div>
          <div><dt>Aggregate memory</dt><dd>{spec(hardware.aggregate_memory_gb ?? hardware.total_memory_gb * hardware.gpu_count, " GB")}</dd></div>
          <div><dt>Memory bandwidth</dt><dd>{spec(hardware.memory_bandwidth_gbs, " GB/s")}</dd></div>
          <div><dt>TDP</dt><dd>{spec(hardware.tdp_watts, " W")}</dd></div>
          <div><dt>FP16</dt><dd>{spec(hardware.tflops_fp16, " TFLOPS")}</dd></div>
          <div><dt>FP8</dt><dd>{spec(hardware.tflops_fp8, " TFLOPS")}</dd></div>
          <div><dt>FP4</dt><dd>{spec(hardware.tflops_fp4, " TFLOPS")}</dd></div>
          <div><dt>Interconnect</dt><dd>{spec(hardware.interconnect)}</dd></div>
          <div><dt>Verified</dt><dd>{spec(hardware.verified)}</dd></div>
        </dl>
        {hardware.spec_url && (
          <a className="primary-link inline-link" href={hardware.spec_url} rel="noreferrer" target="_blank">
            Open manufacturer specification ↗
          </a>
        )}
      </section>
    </section>
  );
}
