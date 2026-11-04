import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build lands in the backend package, so one FastAPI process serves the UI and the API.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../backend/seltzer/static",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
