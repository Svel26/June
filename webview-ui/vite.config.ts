import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: './',
  plugins: [react()],
  build: {
    outDir: "../extension/media",
    emptyOutDir: true,
    // Disable CSS code-splitting so styles emit as a single index.css
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        // Single deterministic entry filename for the webview script
        entryFileNames: "index.js",
        // Inline dynamic imports to avoid generating chunk files
        inlineDynamicImports: true,
        // Deterministic asset filenames (index.css)
        assetFileNames: "index.[ext]"
      }
    }
  }
});