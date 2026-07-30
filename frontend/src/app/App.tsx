import { Navigate, Route, Routes } from "react-router-dom";

import { OverviewPage } from "../features/overview/OverviewPage";
import { ReleaseDetailPage } from "../features/releases/ReleaseDetailPage";
import { ReleaseStreamPage } from "../features/releases/ReleaseStreamPage";
import { AppShell } from "./shell/AppShell";


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
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/releases" element={<ReleaseStreamPage />} />
        <Route path="/releases/:releaseId" element={<ReleaseDetailPage />} />
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
