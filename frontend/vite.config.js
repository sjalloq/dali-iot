import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Builds into the Python package so `dali-iot serve` can ship it.
// In dev, `npm run dev` proxies /api to a local `dali-iot serve`.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "../src/dali_iot/web/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
