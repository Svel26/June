#!/usr/bin/env python3
"""
Minimal dummy MCP-like stdio server for testing.

This script implements a very small JSON-RPC-over-stdio server that responds to:
- method "mcp.list_tools" -> returns a list of available tools
- method "dummy.echo" -> echoes back provided params

Note: This is a lightweight dummy for local integration tests with
[`osae-ide/agent-server/mcp_client.py:325`](osae-ide/agent-server/mcp_client.py:325).
It is not a full MCP implementation but sufficient for discovery/invocation tests.
"""
import sys
import json
import threading
import time
from typing import Any, Dict

TOOLS = [
    {"name": "dummy.echo", "description": "Echo tool that returns provided arguments"},
    {"name": "dummy.ping", "description": "Ping tool that returns 'pong'"},
]


def send_response(resp: Dict[str, Any]) -> None:
    """Write a JSON-RPC response object to stdout (newline-delimited) and flush."""
    sys.stdout.write(json.dumps(resp, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle_request(req: Dict[str, Any]) -> None:
    """Handle an incoming JSON-RPC request dict and send an appropriate response."""
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})

    # Build a basic response template
    resp: Dict[str, Any] = {"jsonrpc": "2.0", "id": req_id}

    try:
        if method == "mcp.list_tools":
            resp["result"] = TOOLS
            send_response(resp)
            return

        if method in ("dummy.echo", "dummy:echo"):
            # Just echo the params back
            resp["result"] = {"echo": params}
            send_response(resp)
            return

        if method in ("dummy.ping", "dummy:ping"):
            resp["result"] = {"pong": True}
            send_response(resp)
            return

        # Unknown method -> JSON-RPC error
        resp["error"] = {"code": -32601, "message": f"Method not found: {method}"}
        send_response(resp)
    except Exception as exc:
        err = {"code": -32000, "message": "Server error", "data": str(exc)}
        send_response({"jsonrpc": "2.0", "id": req_id, "error": err})


def stdin_reader(stop_event: threading.Event) -> None:
    """
    Read newline-delimited JSON messages from stdin.
    Each line is expected to be a complete JSON-RPC object.
    """
    while not stop_event.is_set():
        line = sys.stdin.readline()
        if not line:
            # EOF
            break
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            # If it's a batch (list), handle each entry
            if isinstance(obj, list):
                for item in obj:
                    handle_request(item)
            else:
                handle_request(obj)
        except json.JSONDecodeError:
            # Ignore malformed lines, but continue running
            continue
        except Exception:
            continue


def main() -> None:
    # Print a small banner to stderr so subprocess managers can see the process started.
    print("mcp-dummy-server: starting", file=sys.stderr)
    sys.stderr.flush()

    stop_event = threading.Event()
    reader_thread = threading.Thread(target=stdin_reader, args=(stop_event,), daemon=True)
    reader_thread.start()

    try:
        # Keep the process alive while the reader thread runs.
        while reader_thread.is_alive():
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        reader_thread.join(timeout=1.0)
        print("mcp-dummy-server: stopping", file=sys.stderr)
        sys.stderr.flush()


if __name__ == "__main__":
    main()