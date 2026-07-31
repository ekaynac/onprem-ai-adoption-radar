import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";

import { App } from "./app/App";
import { AppProviders } from "./app/providers";
import "./design/tokens.css";
import "./design/global.css";


const Router = import.meta.env.MODE === "static" ? HashRouter : BrowserRouter;


createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <AppProviders>
      <Router>
        <App />
      </Router>
    </AppProviders>
  </StrictMode>,
);
