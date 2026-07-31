import { Navigate, Route, Routes } from "react-router-dom";

import { CatalogPage } from "../features/catalog/CatalogPage";
import { HardwarePage } from "../features/catalog/HardwarePage";
import { ModelDetailPage } from "../features/catalog/ModelDetailPage";
import { PlatformDetailPage } from "../features/catalog/PlatformDetailPage";
import { PlatformsPage } from "../features/catalog/PlatformsPage";
import { ResearchPage } from "../features/catalog/ResearchPage";
import { ComparePage } from "../features/compare/ComparePage";
import { IntegrationsPage } from "../features/operations/IntegrationsPage";
import { ReviewQueuePage } from "../features/operations/ReviewQueuePage";
import { SourceHealthPage } from "../features/operations/SourceHealthPage";
import { WatchlistsPage } from "../features/operations/WatchlistsPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { PlannerPage } from "../features/planner/PlannerPage";
import { ReleaseDetailPage } from "../features/releases/ReleaseDetailPage";
import { ReleaseStreamPage } from "../features/releases/ReleaseStreamPage";
import { WorkspacePage } from "../features/workspaces/WorkspacePage";
import { AppShell } from "./shell/AppShell";


export function App({
  staticMode = import.meta.env.MODE === "static",
}: {
  staticMode?: boolean;
}) {
  return (
    <Routes>
      <Route element={<AppShell staticMode={staticMode} />}>
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/releases" element={<ReleaseStreamPage />} />
        <Route path="/releases/:releaseId" element={<ReleaseDetailPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/catalog/:releaseId" element={<ModelDetailPage />} />
        <Route path="/platforms" element={<PlatformsPage />} />
        <Route path="/platforms/:platformId" element={<PlatformDetailPage />} />
        <Route path="/hardware" element={<HardwarePage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/compare" element={<ComparePage />} />
        {!staticMode && <Route path="/planner" element={<PlannerPage />} />}
        {!staticMode && <Route path="/workspaces" element={<WorkspacePage />} />}
        <Route path="/operations" element={<SourceHealthPage />} />
        {!staticMode && (
          <Route path="/operations/reviews" element={<ReviewQueuePage />} />
        )}
        {!staticMode && <Route path="/watchlists" element={<WatchlistsPage />} />}
        <Route path="/integrations" element={<IntegrationsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/overview" replace />} />
    </Routes>
  );
}
