import { useActiveWorkspaceId } from "../workspaces/workspaceStore";


export function WatchlistsPage() {
  const workspaceId = useActiveWorkspaceId();
  return (
    <section className="page-stack">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Monitor · Watchlists</p>
          <h1>Route only the changes that matter to this estate</h1>
          <p className="lede">Model families, platforms, lifecycle states, and categories can define a private feed channel.</p>
        </div>
      </header>
      <div className="panel">
        {workspaceId ? (
          <>
            <strong>Active workspace: {workspaceId}</strong>
            <p className="claim-reason">Watchlists are stored in the versioned workspace document and never enter public feeds.</p>
          </>
        ) : (
          <div className="empty-state compact">
            <strong>Select a workspace first</strong>
            <span>Public baseline mode has no private watchlist state.</span>
          </div>
        )}
      </div>
    </section>
  );
}
