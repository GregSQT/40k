// frontend/vite.config.ts
//
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";
import { dirname } from "path";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
  plugins: [react()],
  publicDir: 'public',
  server: {
    fs: {
      allow: ['..'] // Allow serving files from parent directory
    }
  },
  build: {
    sourcemap: true,
    rollupOptions: {
      output: {
        sourcemapBaseUrl: 'http://localhost:5173/'
      }
    }
  },
  resolve: {
    alias: {
    '@': path.resolve(__dirname, 'src'),
    '@roster': path.resolve(__dirname, 'src/roster'),
    '@data': path.resolve(__dirname, 'src/data'),
    '@components': path.resolve(__dirname, 'src/components'),
    '@images': path.resolve(__dirname, '../src/images'),
    '@ai': path.resolve(__dirname, '../ai'),
    "@config": path.resolve(__dirname, "../config"),
    },
  },
});