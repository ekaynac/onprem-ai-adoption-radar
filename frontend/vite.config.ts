import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Static site only: relative base so it works under the GitHub Pages subpath.
// For `npm run dev`, put a pulse.v1.json in public/data/ (git-ignored), e.g.
// from `uv run radar pulse export --out _site`.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../build/frontend",
    emptyOutDir: true,
  },
});
