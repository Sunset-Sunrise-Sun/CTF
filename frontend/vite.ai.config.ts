import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "127.0.0.1",
    port: 15174,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:18002",
        changeOrigin: true,
      },
    },
  },
});
