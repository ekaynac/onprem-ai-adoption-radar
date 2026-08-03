import { NavLink } from "react-router-dom";

import { usePublicSnapshot } from "../../features/catalog/catalogQueries";
import { isSourceHealthy } from "../../features/operations/sourceHealth";


const navigation = [
  {
    label: "Workspace",
    items: [
      { to: "/overview", label: "Overview", mark: "OV" },
      { to: "/workspaces", label: "Workspace profiles", mark: "WS", liveOnly: true },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/releases", label: "Release stream", mark: "RS" },
      { to: "/catalog", label: "Catalog", mark: "CA" },
      { to: "/projects", label: "GitHub projects", mark: "GH" },
      { to: "/platforms", label: "Platforms", mark: "PL" },
      { to: "/hardware", label: "Hardware", mark: "HW" },
      { to: "/research", label: "Research", mark: "RE" },
    ],
  },
  {
    label: "Decide",
    items: [
      { to: "/compare", label: "Compare", mark: "CO" },
      { to: "/planner", label: "Deployment planner", mark: "DP", liveOnly: true },
    ],
  },
  {
    label: "Monitor",
    items: [
      { to: "/operations", label: "Operations", mark: "OP" },
      { to: "/operations/reviews", label: "Review queue", mark: "RQ", liveOnly: true },
      { to: "/watchlists", label: "Watchlists", mark: "WL", liveOnly: true },
    ],
  },
  {
    label: "Integrate",
    items: [{ to: "/integrations", label: "API & feeds", mark: "IF" }],
  },
] as const;

const classicRadar = [
  { href: "models.html", label: "Classic models", mark: "MO" },
  { href: "platforms.html", label: "Classic platforms", mark: "PF" },
  { href: "techniques.html", label: "Classic techniques", mark: "TE" },
  { href: "trending.html", label: "Classic trending", mark: "TR" },
  { href: "history.html", label: "Classic history", mark: "HI" },
  { href: "compare.html", label: "Classic compare", mark: "CP" },
] as const;


export function Sidebar({ staticMode }: { staticMode: boolean }) {
  const snapshot = usePublicSnapshot();
  const sources = snapshot.data?.source_health.source_health ?? [];
  const latestDigest = snapshot.data?.latest_digest;
  const failures = sources.filter((source) => !isSourceHealthy(source)).length;
  return (
    <aside className="sidebar">
      <div className="brand-lockup">
        <span className="brand-glyph" aria-hidden="true">M</span>
        <div>
          <strong>On-Prem</strong>
          <span>Intelligence</span>
        </div>
      </div>
      <nav aria-label="Primary" className="primary-nav">
        {navigation.map((group) => (
          <div className="nav-group" key={group.label}>
            <p>{group.label}</p>
            {group.items
              .filter((item) => !("liveOnly" in item && item.liveOnly && staticMode))
              .map((item) => (
              <NavLink
                to={item.to}
                key={item.to}
                className={({ isActive }) =>
                  `nav-link${isActive ? " nav-link-active" : ""}`
                }
              >
                <span className="nav-mark" aria-hidden="true">{item.mark}</span>
                <span>{item.label}</span>
              </NavLink>
              ))}
          </div>
        ))}
        <div className="nav-group classic-nav">
          <p>Classic radar</p>
          <span className="classic-nav-note">Deep legacy views during restoration</span>
          {classicRadar.map((item) => (
            <a className="nav-link" href={item.href} key={item.href}>
              <span className="nav-mark" aria-hidden="true">{item.mark}</span>
              <span>{item.label}</span>
            </a>
          ))}
          {latestDigest && (
            <a className="nav-link" href={latestDigest.html_url}>
              <span className="nav-mark" aria-hidden="true">WD</span>
              <span>Latest weekly digest</span>
            </a>
          )}
        </div>
      </nav>
      <div className="sidebar-foot">
        <span
          className={`health-dot${failures ? " health-dot-warning" : ""}`}
          aria-hidden="true"
        />
        <div>
          <strong>
            {snapshot.isLoading
              ? "Checking source mesh"
              : failures
                ? `${failures} sources need attention`
                : `${sources.length} sources monitored`}
          </strong>
          <span>Two-hour discovery policy</span>
        </div>
      </div>
    </aside>
  );
}
