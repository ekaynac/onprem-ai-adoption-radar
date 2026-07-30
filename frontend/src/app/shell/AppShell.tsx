import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";


export function AppShell() {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-frame">
        <TopBar />
        <main className="app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
