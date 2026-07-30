import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./shell/AppShell";


function OverviewFoundation() {
  return (
    <section className="page-stack" aria-labelledby="overview-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Architect Workspace</p>
          <h1 id="overview-title">What changed since your last visit</h1>
          <p className="lede">
            New releases, verification progress, deployment fit, and source
            health in one decision surface.
          </p>
        </div>
        <div className="freshness-stamp" aria-label="Freshness objective">
          <span className="pulse-dot" aria-hidden="true" />
          Discovery target: under 2 hours
        </div>
      </header>
      <div className="foundation-grid" aria-label="Command center preview">
        <article className="surface hero-surface">
          <p className="surface-label">Release intelligence</p>
          <strong>Live discovery stream ready</strong>
          <span>Detected → Verified → Qualified → Recommended</span>
        </article>
        <article className="surface">
          <p className="surface-label">Decision posture</p>
          <strong>Balanced decisions</strong>
          <span>Evidence, confidence, and deployment constraints together.</span>
        </article>
        <article className="surface">
          <p className="surface-label">Operating model</p>
          <strong>Automated with review exceptions</strong>
          <span>Human attention is reserved for conflicts and uncertainty.</span>
        </article>
      </div>
    </section>
  );
}


function ComingSoon() {
  return (
    <section className="page-stack">
      <p className="eyebrow">Architect Workspace</p>
      <h1>Intelligence surface</h1>
      <p className="lede">This workspace is connected to the shared command center.</p>
    </section>
  );
}


export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/overview" element={<OverviewFoundation />} />
        <Route path="/releases" element={<ComingSoon />} />
        <Route path="/catalog" element={<ComingSoon />} />
        <Route path="/platforms" element={<ComingSoon />} />
        <Route path="/research" element={<ComingSoon />} />
        <Route path="/compare" element={<ComingSoon />} />
        <Route path="/planner" element={<ComingSoon />} />
        <Route path="/workspaces" element={<ComingSoon />} />
        <Route path="/operations" element={<ComingSoon />} />
        <Route path="/integrations" element={<ComingSoon />} />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  );
}
