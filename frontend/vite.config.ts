// frontend/vite.config.ts
//
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";
import { fileURLToPath } from "url";
import { dirname } from "path";
import fs from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
  plugins: [
    react(),
    // Plugin to serve ai/event_log files directly
    {
      name: 'serve-ai-event-log',
      configureServer(server) {
        server.middlewares.use('/ai/event_log', (req, res, next) => {
          try {
            const filename = req.url?.substring(1); // Remove leading /
            if (!filename) {
              res.statusCode = 400;
              res.end('Invalid request');
              return;
            }
            const filePath = path.join(__dirname, '..', 'ai', 'event_log', filename);
            
            if (fs.existsSync(filePath)) {
              const content = fs.readFileSync(filePath, 'utf8');
              res.setHeader('Content-Type', 'application/json');
              res.setHeader('Access-Control-Allow-Origin', '*');
              res.end(content);
            } else {
              res.statusCode = 404;
              res.end('File not found');
            }
          } catch (error) {
            res.statusCode = 500;
            res.end('Error reading file');
          }
        });
        
        // Add API endpoint to list replay files
        server.middlewares.use('/api/replay-files', (req, res, next) => {
          try {
            const eventLogDir = path.join(__dirname, '..', 'ai', 'event_log');
            const files = fs.readdirSync(eventLogDir);
            const replayFiles = files.filter(file => 
              file.startsWith('training_replay_') && file.endsWith('.json')
            );
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Access-Control-Allow-Origin', '*');
            res.end(JSON.stringify(replayFiles));
          } catch (error) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: 'Cannot read ai/event_log directory' }));
          }
        });
      }
    }
  ],
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
    "@shared": path.resolve(__dirname, "../shared"),
    },
  },
});