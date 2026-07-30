import { WorkspaceSwitcher } from "../../features/workspaces/WorkspaceSwitcher";


export function TopBar() {
  return (
    <header className="topbar">
      <label className="command-search">
        <span className="sr-only">Search intelligence</span>
        <span aria-hidden="true">⌕</span>
        <input
          type="search"
          placeholder="Search models, platforms, evidence…"
        />
        <kbd>⌘ K</kbd>
      </label>
      <div className="topbar-actions">
        <WorkspaceSwitcher />
        <button className="icon-button" type="button" aria-label="Review exceptions">
          <span aria-hidden="true">!</span>
        </button>
        <div className="persona">
          <span className="avatar" aria-hidden="true">IA</span>
          <div>
            <strong>Infrastructure Architect</strong>
            <span>Local command center</span>
          </div>
        </div>
      </div>
    </header>
  );
}
