import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
export default defineConfig(function (_a) {
    var mode = _a.mode;
    return ({
        plugins: [react()],
        base: mode === "static" ? "./" : "/",
        publicDir: "../src/radar/web/static",
        build: {
            outDir: "../build/frontend",
            emptyOutDir: true,
        },
        server: {
            proxy: {
                "/api": "http://127.0.0.1:8765",
            },
        },
    });
});
