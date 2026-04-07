import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const configDir = path.dirname(fileURLToPath(import.meta.url));
const rootDir = fs.realpathSync(configDir);

export default defineConfig({
  root: rootDir,
  base: "./",
  plugins: [react()],
  resolve: {
    preserveSymlinks: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    rollupOptions: {
      input: path.join(rootDir, "index.html"),
    },
  },
});
