import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

import { resolveApiProxyTarget } from "./vite-env-config";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, "..", "");
  const apiProxyTarget = resolveApiProxyTarget(
    env.VITE_API_PROXY_TARGET,
    env.API_PORT,
  );

  return {
  envDir: "..",
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          const moduleId = id.replace(/\\/g, "/");
          if (moduleId.includes("/node_modules/katex/")) return "vendor-katex";
          if (
            moduleId.includes("/node_modules/react-markdown/") ||
            moduleId.includes("/node_modules/remark-") ||
            moduleId.includes("/node_modules/rehype-") ||
            moduleId.includes("/node_modules/unified/") ||
            moduleId.includes("/node_modules/micromark")
          ) {
            return "vendor-markdown";
          }
          if (
            moduleId.includes("/node_modules/react/") ||
            moduleId.includes("/node_modules/react-dom/") ||
            moduleId.includes("/node_modules/react-router/") ||
            moduleId.includes("/node_modules/scheduler/")
          ) {
            return "vendor-react";
          }
          if (
            moduleId.includes("/node_modules/@tanstack/query-core/") ||
            moduleId.includes("/node_modules/@tanstack/react-query/") ||
            moduleId.includes("/node_modules/openapi-fetch/")
          ) {
            return "vendor-data-client";
          }
          if (
            moduleId.includes("/node_modules/@ant-design/icons/") ||
            moduleId.includes("/node_modules/@ant-design/icons-svg/") ||
            moduleId.includes("/node_modules/lucide-react/")
          ) {
            return "vendor-icons";
          }
          if (
            moduleId.includes("/node_modules/framer-motion/") ||
            moduleId.includes("/node_modules/motion-dom/") ||
            moduleId.includes("/node_modules/motion-utils/") ||
            moduleId.includes("/node_modules/motion/")
          ) {
            return "vendor-motion";
          }
          if (
            moduleId.includes("/node_modules/@ant-design/cssinjs/") ||
            moduleId.includes("/node_modules/@ant-design/cssinjs-utils/")
          ) {
            return "vendor-styling";
          }
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    setupFiles: "./src/test/setup.ts",
    maxWorkers: 2,
    testTimeout: 10_000,
  },
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: apiProxyTarget,
        ws: true,
      },
    },
  },
  };
});
