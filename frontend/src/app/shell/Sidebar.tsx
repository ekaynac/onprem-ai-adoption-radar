import megaLogoWhite from "../../assets/brand/mega-logo-white.svg";
import { FEEDS, LANE_LABELS, LANES } from "../../features/pulse/lanes";
import { usePulse } from "../../features/pulse/pulseQueries";


export function Sidebar() {
  const pulse = usePulse();
  const sources = pulse.data?.health.sources ?? [];
  const failing = sources.filter((source) => source.status !== "ok").length;
  const counts = new Map(pulse.data?.lanes.map((lane) => [lane.lane, lane.items.length]) ?? []);
  return (
    <aside className="sidebar">
      <div className="brand-lockup">
        <img src={megaLogoWhite} alt="Mega" className="brand-logo" />
        <div>
          <strong>AI Radar</strong>
          <span>Pulse</span>
        </div>
      </div>
      <nav aria-label="Lanes" className="primary-nav">
        <div className="nav-group">
          <p>What's new</p>
          {LANES.map((lane) => (
            <a className="nav-link" href={`#pulse-lane-${lane}`} key={lane}>
              <span>{LANE_LABELS[lane]}</span>
              {counts.has(lane) && <span className="nav-count">{counts.get(lane)}</span>}
            </a>
          ))}
        </div>
        <div className="nav-group">
          <p>Feeds</p>
          <a className="nav-link" href="pulse.xml">All lanes (RSS)</a>
          {LANES.map((lane) => (
            <a className="nav-link" href={FEEDS[lane]} key={lane}>
              {LANE_LABELS[lane]} (RSS)
            </a>
          ))}
        </div>
      </nav>
      <div className="sidebar-foot">
        <span
          className={`health-dot${
            failing || sources.length === 0 || pulse.data?.health.degraded ? " health-dot-warning" : ""
          }`}
          aria-hidden="true"
        />
        <div>
          <strong>
            {pulse.isLoading
              ? "Checking sources"
              : sources.length === 0
                ? "No source report yet"
                : failing
                  ? `${failing} of ${sources.length} sources need attention`
                  : `${sources.length} sources healthy`}
          </strong>
          <span>{pulse.data?.health.degraded ? "Triage on fallback rules" : "Triage by Jev"}</span>
        </div>
      </div>
    </aside>
  );
}
