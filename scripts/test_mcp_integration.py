#!/usr/bin/env python3
"""
Test runner for MCP dummy server using McpManager bridge.
"""
import sys
import os
import time
import json
import types
import subprocess
import importlib.util
from typing import Any, Dict

# Paths
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MCP_CLIENT_PATH = os.path.join(ROOT, "agent-server", "mcp_client.py")
DUMMY_SERVER_PATH = os.path.join(ROOT, "agent-server", "mcp_dummy_server.py")

# Minimal mcp shim that implements stdio_client and ClientSession used by McpManager
class _StdioClientCM:
    def __init__(self, proc: subprocess.Popen):
        self.proc = proc

    def __enter__(self):
        return _StdioTransport(self.proc)

    def __exit__(self, exc_type, exc, tb):
        # no-op
        return False

class _StdioTransport:
    def __init__(self, proc: subprocess.Popen):
        self.proc = proc
        self._id = 0

    def call_rpc(self, method: str, params: Dict[str, Any]):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        line = json.dumps(payload, separators=(",", ":")) + "\n"
        try:
            # write as text to subprocess stdin
            self.proc.stdin.write(line)
            self.proc.stdin.flush()
        except Exception as exc:
            raise RuntimeError(f"Failed to write to subprocess stdin: {exc}")
        # Read a single line response
        out_line = self.proc.stdout.readline()
        if not out_line:
            raise RuntimeError("No response from MCP server (EOF)")
        try:
            resp = json.loads(out_line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON response: {exc}")
        if "error" in resp:
            raise RuntimeError(f"RPC error: {resp['error']}")
        return resp.get("result")

class _ClientSession:
    def __init__(self, transport: _StdioTransport):
        self._transport = transport

    def call(self, method: str, params: Dict[str, Any]):
        return self._transport.call_rpc(method, params)

    def list_tools(self):
        return self.call("mcp.list_tools", {})

# Insert shim into sys.modules before loading mcp_client so imports resolve to this shim
m = types.ModuleType("mcp")
m.stdio_client = lambda proc: _StdioClientCM(proc)
m.ClientSession = _ClientSession
sys.modules["mcp"] = m

# Load mcp_client module from file so it picks up our shim
spec = importlib.util.spec_from_file_location("mcp_client", MCP_CLIENT_PATH)
mcp_client = importlib.util.module_from_spec(spec)
sys.modules["mcp_client"] = mcp_client
spec.loader.exec_module(mcp_client)  # type: ignore

def main():
    mgr = mcp_client.get_global_manager()

    print("Starting connection to dummy MCP server...")
    try:
        mgr.connect_to_server("dummy", sys.executable, [DUMMY_SERVER_PATH])
    except Exception as exc:
        print(f"connect_to_server failed: {exc}", file=sys.stderr)
        return 1

    time.sleep(0.1)

    try:
        tools = mgr.list_tools()
        print("Discovered tools (server -> tools):")
        print(json.dumps(tools, indent=2))
    except Exception as exc:
        print(f"Listing tools failed: {exc}", file=sys.stderr)
    finally:
        try:
            mgr.disconnect_server("dummy")
        except Exception:
            pass
        mgr.shutdown()
    return 0

if __name__ == "__main__":
    sys.exit(main())