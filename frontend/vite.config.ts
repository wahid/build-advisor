import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development Vite serves the app and forwards /api to Django.
// In production Django serves the built files from /static/.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === "build" ? "/static/" : "/",
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": process.env.VITE_API_TARGET ?? "http://localhost:8000",
    },
  },
  test: {
    environment: "node",
  },
}));
