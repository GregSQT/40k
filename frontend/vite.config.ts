import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0", // Listen on all network interfaces (IPv4 and IPv6)
    port: 5175,
    strictPort: true,
    open: false, // Ne pas ouvrir automatiquement le navigateur
  },
});
