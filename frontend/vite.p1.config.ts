import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// Dedicated launcher config for the independent P1 run.  It never connects to
// the long-lived 8000/8001/8002/5173/5174 services used by other work.
export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 15190,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:18110",
        changeOrigin: true,
      },
    },
  },
});
