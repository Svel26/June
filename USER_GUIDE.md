# OSAE-IDE User Guide

## Prerequisites
- Ollama models (pull these exact model names):

  - `qwen2.5-coder`
  - `deepseek-r1:7b`
  - `nomic-embed-text`

Pull the models with:
```bash
ollama pull qwen2.5coder
ollama pull deepseek-r1:7b
ollama pull nomic-embed-text
```

## Startup
1. Start the RAG server (bundled):

See server file: [`osae-ide/bundled-mcp/rag-server/server.py`](osae-ide/bundled-mcp/rag-server/server.py:1)

PowerShell:
```powershell
cd osae-ide/bundled-mcp/rag-server
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

Bash / macOS / Linux:
```bash
cd osae-ide/bundled-mcp/rag-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

2. Launch the extension in VS Code:
- Open the workspace in VS Code and press F5 to run the "Extension Development Host".
- Ensure the agent server (if used) is running: see [`osae-ide/agent-server/main.py`](osae-ide/agent-server/main.py:1)
- If the extension has a webview UI, build it before debugging:
```bash
cd osae-ide/webview-ui
npm install
npm run build
```

Keep both the RAG server terminal and Extension Development Host open while testing.

## Golden Prompt
Paste this exact prompt into the chat to test the system:

```text
Build a modern React Todo App with drag-and-drop ordering. Use Sandpack to show me the result.
```

## Troubleshooting
- If models fail to pull, ensure Ollama is installed and you are signed in.
- If the RAG server fails to start, check the venv and that requirements are installed.
- If the extension doesn't connect, confirm the RAG server is reachable and ports are not blocked.
