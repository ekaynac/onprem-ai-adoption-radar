import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";


export function AppShell({ staticMode }: { staticMode: boolean }) {
  return (
    <div className="app-shell">
      <Sidebar staticMode={staticMode} />
      <div className="app-frame">
        <TopBar staticMode={staticMode} />
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
