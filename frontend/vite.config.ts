/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The SPA and the API share one origin: Vite proxies /api in dev, the host proxies it in
// production. Cookies stay first-party and CORS is never needed by the app itself.
// VERITA_WEB_PORT / VERITA_API_URL move both ends when the defaults are taken locally.
const webPort = Number(process.env.VERITA_WEB_PORT ?? 5173);
const apiUrl = process.env.VERITA_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: webPort,
    strictPort: true,
    proxy: { "/api": { target: apiUrl, changeOrigin: false } },
  },
  // `vite preview` serves the production bundle the same way (Lighthouse CI audits it).
  preview: { proxy: { "/api": { target: apiUrl, changeOrigin: false } } },
  // assetsInlineLimit 0: no data: URIs, so the CSP keeps font-src/img-src at 'self'.
  build: { sourcemap: true, target: "es2022", assetsInlineLimit: 0 },
  test: {
    environment: "happy-dom",
    include: ["src/**/*.test.{ts,tsx}"], // e2e/*.spec.ts belong to Playwright
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: { modules: { classNameStrategy: "non-scoped" } },
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx", "src/vite-env.d.ts"],
      thresholds: { lines: 85, branches: 80, functions: 85, statements: 85 },
    },
  },
});
