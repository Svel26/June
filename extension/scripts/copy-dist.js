#!/usr/bin/env node
const fs = require('fs');
const path = require('path');

const repoRoot = path.resolve(__dirname, '..');
const webviewDist = path.join(repoRoot, 'webview-ui', 'dist');
const dest = path.join(repoRoot, 'extension', 'media');

if (!fs.existsSync(webviewDist)) {
  console.error('webview-ui/dist not found. Run `npm run build` in webview-ui first.');
  process.exit(1);
}

fs.rmSync(dest, { recursive: true, force: true });
fs.mkdirSync(dest, { recursive: true });

function copyRecursive(src, dst) {
  const entries = fs.readdirSync(src, { withFileTypes: true });
  entries.forEach(entry => {
    const srcPath = path.join(src, entry.name);
    const dstPath = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      fs.mkdirSync(dstPath, { recursive: true });
      copyRecursive(srcPath, dstPath);
    } else {
      fs.copyFileSync(srcPath, dstPath);
    }
  });
}

copyRecursive(webviewDist, dest);
console.log('Copied webview-ui/dist -> extension/media');