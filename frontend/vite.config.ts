import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig(({ mode }) =>
  mode === "demo"
    ? {
        // Design preview: the app on a fake in-browser API, with relative asset paths so the
        // build can be hosted anywhere (`npm run build:demo`).
        plugins: [react(), tailwindcss()],
        base: "./",
        build: { outDir: "dist-demo", emptyOutDir: true, rolldownOptions: { input: "demo.html" } },
      }
    : {
        // The build lands in the backend package, so one FastAPI process serves the UI and the API.
        plugins: [react(), tailwindcss()],
        build: { outDir: "../backend/seltzer/static", emptyOutDir: true },
        server: { port: 5173, proxy: { "/api": "http://localhost:8000" } },
      },
);
