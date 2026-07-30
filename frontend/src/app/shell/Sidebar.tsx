import { NavLink } from "react-router-dom";


const navigation = [
  {
    label: "Workspace",
    items: [
      { to: "/overview", label: "Overview", mark: "OV" },
      { to: "/workspaces", label: "Workspace profiles", mark: "WS" },
    ],
  },
  {
    label: "Intelligence",
    items: [
      { to: "/releases", label: "Release stream", mark: "RS" },
      { to: "/catalog", label: "Catalog", mark: "CA" },
      { to: "/platforms", label: "Platforms", mark: "PL" },
      { to: "/hardware", label: "Hardware", mark: "HW" },
      { to: "/research", label: "Research", mark: "RE" },
    ],
  },
  {
    label: "Decide",
    items: [
      { to: "/compare", label: "Compare", mark: "CO" },
      { to: "/planner", label: "Deployment planner", mark: "DP" },
    ],
  },
  {
    label: "Monitor",
    items: [
      { to: "/operations", label: "Operations", mark: "OP" },
      { to: "/operations/reviews", label: "Review queue", mark: "RQ" },
      { to: "/watchlists", label: "Watchlists", mark: "WL" },
    ],
  },
  {
    label: "Integrate",
    items: [{ to: "/integrations", label: "API & feeds", mark: "IF" }],
  },
] as const;


export function Sidebar() {
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
            {group.items.map((item) => (
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
      </nav>
      <div className="sidebar-foot">
        <span className="health-dot" aria-hidden="true" />
        <div>
          <strong>Source mesh healthy</strong>
          <span>Freshness policy active</span>
        </div>
      </div>
    </aside>
  );
}
