import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { searchForWorkspaceRoot } from "vite";
import { defineConfig } from "vitest/config";

// The API server that `make dev` starts; the dev server forwards `/api` to it.
const API_TARGET = process.env.HIVE_API_URL ?? "http://127.0.0.1:8000";

// The insect graphics of the Python package, shared with its board plots.
const INSECTS_DIR = path.resolve(import.meta.dirname, "../src/hive/assets/svg");

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src"), "@insects": INSECTS_DIR },
  },
  server: {
    proxy: { "/api": { target: API_TARGET, changeOrigin: true } },
    fs: { allow: [searchForWorkspaceRoot(process.cwd()), INSECTS_DIR] },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: { include: [/index\.css/] },
  },
});
