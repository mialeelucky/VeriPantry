import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      // Our own service worker: it handles push notifications (frontend.md §4.4).
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      injectRegister: false,
      manifest: {
        name: "VeriPantry",
        short_name: "VeriPantry",
        description: "Approve your purchasing agent's requests.",
        start_url: "/approvals",
        display: "standalone",
        background_color: "#F7F7F5",
        theme_color: "#F7F7F5",
        icons: [{ src: "/icon.svg", sizes: "any", type: "image/svg+xml", purpose: "any" }],
      },
      devOptions: { enabled: true, type: "module" },
    }),
  ],
  server: { port: 5173, strictPort: true },
  test: { environment: "jsdom", globals: false, setupFiles: [], include: ["src/**/*.test.ts"] },
});
