# OSAE IDE — Development Quickstart

Prerequisites:
- Node.js (v18+)
- Python 3.10+ (for venv creation)
- npm

1. Create Python venv and install dependencies (Unix):
   ./scripts/setup_agent_server.sh

   Windows (PowerShell):
   .\scripts\setup_agent_server.ps1

2. Build the webview UI and copy into the extension:
   npm run build --prefix webview-ui
   node scripts/copy-dist.js

3. Build the extension:
   cd extension
   npm install
   npm run compile

4. Run & Debug:
   - Open this folder in VS Code.
   - Run the "Run Extension" launch target (F5).
   - The extension spawns the agent-server at extension startup using the bundled venv.