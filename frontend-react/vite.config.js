import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds to dist/ which FastAPI serves at "/". During dev, proxy API + WS to :8080.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      "/api": { target: "http://127.0.0.1:8080", ws: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
