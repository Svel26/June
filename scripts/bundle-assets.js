#!/usr/bin/env node
"use strict";

const fs = require('fs');
const fsp = fs.promises;
const path = require('path');
const { exit } = require('process');

const scriptDir = __dirname;
const sources = [
  {
    name: 'agent-server',
    src: path.resolve(scriptDir, '..', 'agent-server'),
    dest: path.resolve(scriptDir, '..', 'extension', 'agent-server'),
    skipDirs: new Set(['venv', '__pycache__']),
    skipFiles: new Set(['.env']),
  },
  {
    name: 'scripts',
    src: path.resolve(scriptDir, '..', 'scripts'),
    dest: path.resolve(scriptDir, '..', 'extension', 'scripts'),
    skipDirs: new Set(),
    skipFiles: new Set(),
  },
  {
    name: 'bundled-mcp',
    src: path.resolve(scriptDir, '..', 'bundled-mcp'),
    dest: path.resolve(scriptDir, '..', 'extension', 'bundled-mcp'),
    skipDirs: new Set(['venv', '__pycache__']),
    skipFiles: new Set(),
  },
];

async function ensureDir(dir) {
  await fsp.mkdir(dir, { recursive: true });
}

function isShFile(p) {
  return p.endsWith('.sh');
}

async function copyRecursive(src, dst, opts) {
  let stat;
  try {
    stat = await fsp.lstat(src);
  } catch (err) {
    console.warn('Skipping missing:', src);
    return;
  }

  if (stat.isDirectory()) {
    const base = path.basename(src);
    if (opts.skipDirs && opts.skipDirs.has(base)) return;
    await ensureDir(dst);
    const entries = await fsp.readdir(src);
    for (const entry of entries) {
      await copyRecursive(path.join(src, entry), path.join(dst, entry), opts);
    }
    return;
  }

  if (stat.isSymbolicLink()) {
    try {
      const link = await fsp.readlink(src);
      try { await fsp.unlink(dst); } catch (e) {}
      await fsp.symlink(link, dst);
    } catch (err) {
      console.warn('Failed to copy symlink:', src, err.message);
    }
    return;
  }

  if (stat.isFile()) {
    const base = path.basename(src);
    if (opts.skipFiles && opts.skipFiles.has(base)) return;
    await ensureDir(path.dirname(dst));
    try {
      await fsp.copyFile(src, dst);
    } catch (err) {
      console.error('Failed to copy file:', src, err.message);
      throw err;
    }
    // Preserve mode (ensure executable bits for .sh are kept)
    try {
      const mode = stat.mode & 0o777;
      await fsp.chmod(dst, mode);
    } catch (err) {
      // chmod may fail on some platforms; warn but continue
      console.warn('Failed to set mode for', dst, err.message);
    }
  }
}

async function copyAll() {
  for (const s of sources) {
    console.log(`Copying ${s.name}: ${s.src} -> ${s.dest}`);
    try {
      await copyRecursive(s.src, s.dest, { skipDirs: s.skipDirs, skipFiles: s.skipFiles });
    } catch (err) {
      console.error(`Error copying ${s.name}:`, err);
      // Continue with next source to keep idempotent behavior
    }
  }
}

async function main() {
  try {
    await copyAll();
    console.log('Asset bundling complete.');
    exit(0);
  } catch (err) {
    console.error('Fatal error during bundling:', err);
    exit(2);
  }
}

if (require.main === module) main();