import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: '../extension/media',
    rollupOptions: {
      output: {
        // Ensure a consistent filename for the webview entry so the extension can reference it reliably
        entryFileNames: 'index.js',
        // Keep chunks in a subfolder with hashes to avoid name collisions during incremental builds
        chunkFileNames: 'chunks/[name]-[hash].js',
        // Emit a single index.css for styles so the extension can reference a stable path
        assetFileNames: (assetInfo: { name?: string }) => {
          if (assetInfo.name && assetInfo.name.endsWith('.css')) {
            return 'index.css';
          }
          return 'assets/[name]-[hash][extname]';
        }
      }
    }
  }
});