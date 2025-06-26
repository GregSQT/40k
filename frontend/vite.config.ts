// frontend/vite.config.ts
//
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";
import { dirname } from "path";
import fs from "fs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
  plugins: [
    react(),
    // Custom plugin to serve ai directory files
    {
      name: 'serve-ai-files',
      configureServer(server) {
        server.middlewares.use('/ai', (req, res, next) => {
          // Serve files from the ai directory
          const filePath = path.join(__dirname, '..', req.url!);
          
          // Check if file exists and serve it
          if (fs.existsSync(filePath)) {
            // Set proper content type for JSON files
            if (req.url!.endsWith('.json')) {
              res.setHeader('Content-Type', 'application/json');
            }
            // Serve the file
            const fileContent = fs.readFileSync(filePath);
            res.end(fileContent);
          } else {
            next();
          }
        });
      }
    }
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@roster': path.resolve(__dirname, 'src/roster'),
      '@data': path.resolve(__dirname, 'src/data'),
      '@components': path.resolve(__dirname, 'src/components'),
      '@images': path.resolve(__dirname, '../src/images'),
      '@ai': path.resolve(__dirname, '../ai'),
    },
  },
  server: {
    fs: {
      // Allow serving files from parent directory to access ai folder
      allow: ['..', '.']
    }
  }
});