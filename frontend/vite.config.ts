import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// FastAPI serves this build from the same origin, under BASE_PATH (e.g. /aicall behind the shared nginx).
// Build with the same BASE_PATH the server uses; empty means the site root.
declare const process: { env: Record<string, string | undefined> }; // Node global, without @types/node
const basePath = (process.env.BASE_PATH ?? "").replace(/^\/+|\/+$/g, "");
const base = basePath ? `/${basePath}/` : "/";

export default defineConfig({
  base,
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { [`${base}api`]: "http://127.0.0.1:8083" } },
  build: { outDir: "dist", sourcemap: false },
  test: { environment: "jsdom" },
});
