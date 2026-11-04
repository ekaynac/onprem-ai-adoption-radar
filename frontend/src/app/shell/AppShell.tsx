import type { PropsWithChildren } from "react";

import megaLogo from "../../assets/brand/mega-logo-blue.svg";
import { Sidebar } from "./Sidebar";


const REPO_URL = "https://github.com/ekaynac/onprem-ai-adoption-radar";
const MEGA_URL = "https://www.megabilgisayar.com.tr";


export function AppShell({ children }: PropsWithChildren) {
  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-frame">
        <main className="app-main">{children}</main>
        <footer className="site-footer">
          <a href={MEGA_URL} rel="noreferrer" target="_blank" aria-label="Mega Bilgisayar">
            <img src={megaLogo} alt="" className="site-footer-logo" />
          </a>
          <div>
            <p>
              Auto-updated every two hours · <a href="pulse.xml">RSS</a> ·{" "}
              <a href={REPO_URL} rel="noreferrer" target="_blank">source on GitHub</a>
            </p>
            <p>
              Built by Enes Kaynakcı · Software Engineer at{" "}
              <a href={MEGA_URL} rel="noreferrer" target="_blank">Mega Bilgisayar Tic. Ltd. Şti.</a>
            </p>
          </div>
        </footer>
      </div>
    </div>
  );
}
