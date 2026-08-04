import { Navigate, Route, Routes } from "react-router-dom";

import { CatalogPage } from "../features/catalog/CatalogPage";
import { HardwarePage } from "../features/catalog/HardwarePage";
import { ModelDetailPage } from "../features/catalog/ModelDetailPage";
import { PlatformDetailPage } from "../features/catalog/PlatformDetailPage";
import { PlatformsPage } from "../features/catalog/PlatformsPage";
import { ProjectDetailPage } from "../features/catalog/ProjectDetailPage";
import { ProjectsPage } from "../features/catalog/ProjectsPage";
import { HardwareDetailPage } from "../features/catalog/HardwareDetailPage";
import { ResearchDetailPage } from "../features/catalog/ResearchDetailPage";
import { ResearchPage } from "../features/catalog/ResearchPage";
import { ComparePage } from "../features/compare/ComparePage";
import { IntegrationsPage } from "../features/operations/IntegrationsPage";
import { ReviewQueuePage } from "../features/operations/ReviewQueuePage";
import { SourceHealthPage } from "../features/operations/SourceHealthPage";
import { OverviewPage } from "../features/overview/OverviewPage";
import { HomePage } from "../features/home/HomePage";
import { AdvisorPage } from "../features/advisor/AdvisorPage";
import { DeskPage } from "../features/desk/DeskPage";
import { NewsroomPage } from "../features/newsroom/NewsroomPage";
import { PlannerPage } from "../features/planner/PlannerPage";
import { TrendingPage } from "../features/trending/TrendingPage";
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
        <Route path="/" element={<HomePage />} />
        <Route path="/overview" element={<OverviewPage staticMode={staticMode} />} />
        <Route path="/desk" element={<DeskPage staticMode={staticMode} />} />
        <Route path="/releases" element={<ReleaseStreamPage />} />
        <Route path="/releases/:releaseId" element={<ReleaseDetailPage />} />
        <Route path="/trending" element={<TrendingPage />} />
        <Route path="/newsroom" element={<NewsroomPage />} />
        <Route path="/catalog" element={<CatalogPage />} />
        <Route path="/catalog/:releaseId" element={<ModelDetailPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/projects/:projectName" element={<ProjectDetailPage />} />
        <Route path="/platforms" element={<PlatformsPage />} />
        <Route path="/platforms/:platformId" element={<PlatformDetailPage />} />
        <Route path="/hardware" element={<HardwarePage />} />
        <Route path="/hardware/:hardwareId" element={<HardwareDetailPage />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/research/:researchId" element={<ResearchDetailPage />} />
        <Route path="/compare" element={<ComparePage />} />
        <Route path="/advisor" element={<AdvisorPage staticMode={staticMode} />} />
        <Route path="/planner" element={<PlannerPage staticMode={staticMode} />} />
        <Route path="/workspaces" element={<WorkspacePage staticMode={staticMode} />} />
        <Route path="/operations" element={<SourceHealthPage staticMode={staticMode} />} />
        {!staticMode && (
          <Route path="/operations/reviews" element={<ReviewQueuePage />} />
        )}
        <Route
          path="/integrations"
          element={<IntegrationsPage staticMode={staticMode} />}
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
