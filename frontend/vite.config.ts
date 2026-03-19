import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["favicon.png", "apple-touch-icon.png", "icon.svg"],
      manifest: {
        name: "CCTV Console",
        short_name: "CCTV",
        description: "Система видеонаблюдения с распознаванием лиц",
        theme_color: "#0f172a",
        background_color: "#0b1021",
        display: "standalone",
        orientation: "any",
        start_url: "/",
        scope: "/",
        icons: [
          { src: "icons/icon-72x72.png", sizes: "72x72", type: "image/png" },
          { src: "icons/icon-96x96.png", sizes: "96x96", type: "image/png" },
          { src: "icons/icon-128x128.png", sizes: "128x128", type: "image/png" },
          { src: "icons/icon-144x144.png", sizes: "144x144", type: "image/png" },
          { src: "icons/icon-152x152.png", sizes: "152x152", type: "image/png" },
          {
            src: "icons/icon-192x192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any maskable",
          },
          { src: "icons/icon-384x384.png", sizes: "384x384", type: "image/png" },
          {
            src: "icons/icon-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any maskable",
          },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        runtimeCaching: [
          {
            // Cache API calls (short-lived)
            urlPattern: /\/api\/.*/i,
            handler: "NetworkFirst",
            options: {
              cacheName: "api-cache",
              expiration: { maxEntries: 50, maxAgeSeconds: 300 },
            },
          },
          {
            // Cache camera snapshots
            urlPattern: /\/snapshots\/.*/i,
            handler: "CacheFirst",
            options: {
              cacheName: "snapshot-cache",
              expiration: { maxEntries: 100, maxAgeSeconds: 86400 },
            },
          },
        ],
      },
    }),
  ],
});
