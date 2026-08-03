import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { WorkspaceSwitcher } from "../../features/workspaces/WorkspaceSwitcher";


export function TopBar({ staticMode }: { staticMode: boolean }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function focusSearch(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
      }
    }
    window.addEventListener("keydown", focusSearch);
    return () => window.removeEventListener("keydown", focusSearch);
  }, []);

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const normalized = query.trim();
    navigate({
      pathname: "/catalog",
      search: normalized ? `?${new URLSearchParams({ q: normalized })}` : "",
    });
  }

  return (
    <header className="topbar">
      <form className="command-search" role="search" onSubmit={submit}>
        <span className="sr-only">Search intelligence</span>
        <span aria-hidden="true">⌕</span>
        <input
          ref={input}
          type="search"
          aria-label="Search intelligence"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search models, platforms, evidence…"
        />
        <kbd>⌘ K</kbd>
      </form>
      <div className="topbar-actions">
        {!staticMode && <WorkspaceSwitcher />}
        {!staticMode && (
          <button className="icon-button" type="button" aria-label="Review exceptions">
            <span aria-hidden="true">!</span>
          </button>
        )}
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
