import { CatalogTrust } from "./CatalogTrust";
import { PriorityIntelligence } from "./PriorityIntelligence";
import { RecommendedActions } from "./RecommendedActions";
import {
  useActiveWorkspaceId,
  useCatalogHealth,
  usePriorityReleases,
  useRecommendedActions,
} from "../releases/releaseQueries";
import { usePublicSnapshot } from "../catalog/catalogQueries";


function QueryFailure({ retry }: { retry: () => void }) {
  return (
    <div className="error-state" role="alert">
      <strong>Intelligence could not be refreshed</strong>
      <button type="button" onClick={retry}>Try again</button>
    </div>
  );
}


export function OverviewPage({ staticMode = false }: { staticMode?: boolean }) {
  const workspaceId = useActiveWorkspaceId();
  const releases = usePriorityReleases(workspaceId);
  const actions = useRecommendedActions(workspaceId);
  const health = useCatalogHealth();
  const snapshot = usePublicSnapshot(staticMode);
  const failed = releases.isError || actions.isError || health.isError;

  return (
    <section className="page-stack" aria-labelledby="overview-title">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Architect Workspace · Decision briefing</p>
          <h1 id="overview-title">What changed since your last visit</h1>
          <p className="lede">
            {staticMode
              ? "Public evidence snapshot. Detection is separated from verified deployment advice."
              : "Your estate and policies applied. Detection is separated from verified deployment advice."}
          </p>
        </div>
        <div className="freshness-stamp" aria-label="Freshness objective">
          <span className="pulse-dot" aria-hidden="true" />
          Discovery target: under 2 hours
        </div>
      </header>

      {failed ? (
        <QueryFailure
          retry={() => {
            void releases.refetch();
            void actions.refetch();
            void health.refetch();
          }}
        />
      ) : releases.isLoading || actions.isLoading || health.isLoading ? (
        <div className="loading-grid" aria-label="Loading intelligence">
          <span />
          <span />
          <span />
        </div>
      ) : (
        <>
          <PriorityIntelligence items={releases.data?.items ?? []} />
          <div className="overview-grid">
            <RecommendedActions items={actions.data?.items ?? []} />
            <CatalogTrust health={health.data} />
          </div>
          <p className="data-timestamp">
            {staticMode
              ? `Snapshot generated ${snapshot.data?.generated_at
                  ? new Date(snapshot.data.generated_at).toLocaleString()
                  : "at an unavailable time"} · checked when this page loaded`
              : "Live API · checked automatically every minute"}
          </p>
        </>
      )}
    </section>
  );
}
