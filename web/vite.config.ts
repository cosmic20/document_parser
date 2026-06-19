import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: proxy API + WebSocket to the local FastAPI backend (docparse web, port 8765).
// Prod: the built app is served by FastAPI at the same origin, so relative /api works.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8765", changeOrigin: true, ws: true },
    },
  },
});
