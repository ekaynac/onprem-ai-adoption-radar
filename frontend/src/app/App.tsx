import { Navigate, Route, Routes } from "react-router-dom";

import { CatalogPage } from "../features/catalog/CatalogPage";
import { HardwarePage } from "../features/catalog/HardwarePage";
import { ModelDetailPage } from "../features/catalog/ModelDetailPage";
import { PlatformDetailPage } from "../features/catalog/PlatformDetailPage";
import { PlatformsPage } from "../features/catalog/PlatformsPage";
import { ResearchPage } from "../features/catalog/ResearchPage";
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
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/catalog/:releaseId" element={<ModelDetailPage />} />
        <Route path="/platforms" element={<PlatformsPage />} />
        <Route path="/platforms/:platformId" element={<PlatformDetailPage />} />
        <Route path="/hardware" element={<HardwarePage />} />
        <Route path="/research" element={<ResearchPage />} />
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
