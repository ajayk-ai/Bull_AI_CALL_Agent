import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs on port 8083; in production FastAPI serves this build from the same origin.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8083" } },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom" },
});
