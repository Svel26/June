"""
MCP bridge: McpManager

Implements a thin manager that spawns stdio-based MCP servers, creates
ClientSession wrappers and routes tool discovery / invocation.

This file intentionally contains only protocol/connection handling and
does not implement any tool-specific logic.
"""
from __future__ import annotations

import subprocess
import threading
import time
import json
import logging
import inspect
from typing import Any, Dict, List, Optional, Tuple

import mcp

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())


class McpConnectionError(RuntimeError):
    pass


class McpManager:
    """
    Manage multiple MCP stdio servers running as subprocesses.

    Typical usage:
        mgr = McpManager()
        mgr.connect_to_server("fs", "/path/to/fs-mcp", ["--serve"])
        tools = mgr.list_tools()
        result = mgr.call_tool("fs:read_file", {"path": "README.md"})
    """

    def __init__(self) -> None:
        # servers[name] = {
        #   "proc": Popen,
        #   "cmgr": stdio_client_context_manager (entered via __enter__),
        #   "client": underlying stdio client object,
        #   "session": mcp.ClientSession,
        #   "tools": {tool_name: tool_meta, ...},
        #   "lock": threading.Lock()
        # }
        self._servers: Dict[str, Dict[str, Any]] = {}
        self._global_lock = threading.RLock()

    def connect_to_server(self, name: str, command: str, args: List[str]) -> None:
        """
        Spawn an MCP server process and initialize an mcp.ClientSession.

        - name: logical name for the server (must be unique)
        - command: executable path
        - args: list of arguments
        """
        with self._global_lock:
            if name in self._servers:
                raise McpConnectionError(f"MCP server with name '{name}' already connected")

            cmd = [command] + list(args)
            logger.info("Starting MCP server %s: %s", name, cmd)
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )

            # Allow small startup time for server to initialize
            time.sleep(0.25)

            # Use mcp.stdio_client and mcp.ClientSession per SDK guidance.
            # We try to enter the stdio_client context manually so the session
            # can be used for the lifetime of the subprocess.
            try:
                cmgr = mcp.stdio_client(proc)
                # Enter the context manager to obtain the client transport.
                client = cmgr.__enter__()  # type: ignore[attr-defined]
                session = mcp.ClientSession(client)
            except Exception as exc:
                # Ensure process is killed on failure to initialise
                try:
                    proc.kill()
                except Exception:
                    pass
                raise McpConnectionError(f"Failed to initialize MCP client for '{name}': {exc}") from exc

            server_entry: Dict[str, Any] = {
                "proc": proc,
                "cmgr": cmgr,
                "client": client,
                "session": session,
                "tools": {},  # filled by discovery
                "lock": threading.RLock(),
            }

            self._servers[name] = server_entry

            # Attempt to discover tools immediately (best-effort)
            try:
                tools = self._discover_tools(session)
                server_entry["tools"] = tools or {}
                logger.info("Discovered %d tools for server %s", len(server_entry["tools"]), name)
            except Exception as e:
                logger.warning("Tool discovery failed for server %s: %s", name, e)

    def _discover_tools(self, session: mcp.ClientSession) -> Dict[str, Any]:
        """
        Attempt to query the session for exposed tools.

        Tries common method names used by MCP SDKs and falls back gracefully.
        Returns a mapping tool_name -> metadata (may be None if not available).
        """
        # Common method names to try
        candidates = ["list_tools", "get_tools", "tools", "discover_tools"]
        for cand in candidates:
            if hasattr(session, cand):
                try:
                    method = getattr(session, cand)
                    tools = method() if callable(method) else method
                    # Normalise to dict
                    if isinstance(tools, dict):
                        return tools
                    if isinstance(tools, list):
                        return {t.get("name", str(t)): t for t in tools}
                except Exception:
                    # continue to other candidates
                    logger.debug("Candidate %s on session raised during discovery", cand, exc_info=True)

        # As a last resort, try to call an RPC named "mcp.list_tools" via generic call API
        try:
            if hasattr(session, "call"):
                maybe = session.call("mcp.list_tools", {})
                # call might return a list/dict or a coroutine
                if inspect.isawaitable(maybe):
                    import asyncio

                    maybe = asyncio.run(maybe)
                if isinstance(maybe, dict):
                    return maybe
                if isinstance(maybe, list):
                    return {t.get("name", str(t)): t for t in maybe}
        except Exception:
            logger.debug("Fallback discovery via session.call failed", exc_info=True)

        # Nothing discovered
        return {}

    def list_tools(self) -> Dict[str, Dict[str, Any]]:
        """
        Aggregate tools from all connected servers.

        Returns a dict mapping server_name -> {tool_name: metadata}
        """
        with self._global_lock:
            out: Dict[str, Dict[str, Any]] = {}
            for name, entry in self._servers.items():
                tools = entry.get("tools") or {}
                # if tools is callable or a session attribute, attempt re-discovery lazily
                if not isinstance(tools, dict) or not tools:
                    try:
                        tools = self._discover_tools(entry["session"])
                        entry["tools"] = tools or {}
                    except Exception:
                        tools = entry.get("tools") or {}
                out[name] = tools
            return out

    def _resolve_tool(self, name: str) -> Tuple[str, str]:
        """
        Resolve a tool specification to (server_name, tool_name).

        Accepted formats:
          - "server:tool"
          - "server.tool"
          - "tool" (attempts to find a unique tool across servers)
        """
        if ":" in name:
            server, tool = name.split(":", 1)
            return server, tool
        if "." in name:
            server, tool = name.split(".", 1)
            return server, tool

        # search across servers
        matches: List[Tuple[str, str]] = []
        tools_map = self.list_tools()
        for server, tools in tools_map.items():
            if name in tools:
                matches.append((server, name))
            else:
                # some tool metadata may include 'name' field inside list form
                for tname in tools.keys():
                    if tname == name:
                        matches.append((server, tname))

        if not matches:
            raise McpConnectionError(f"Tool '{name}' not found on any connected server")
        if len(matches) > 1:
            servers = ", ".join(s for s, _ in matches)
            raise McpConnectionError(f"Ambiguous tool name '{name}' found on servers: {servers}. Use 'server:tool' form.")
        return matches[0]

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """
        Route the tool call to the appropriate server and invoke the tool.

        - name: either "server:tool", "server.tool", or a unique "tool"
        - arguments: dict of arguments to pass to the tool

        Returns whatever the remote tool returns (decoded if necessary).
        """
        server_name, tool_name = self._resolve_tool(name)

        with self._global_lock:
            if server_name not in self._servers:
                raise McpConnectionError(f"Server '{server_name}' is not connected")

            entry = self._servers[server_name]
            session: mcp.ClientSession = entry["session"]

        # Preferred method names for tool invocation on the session
        invoke_candidates = ["call_tool", "call", "invoke", "execute", "run_tool", "run"]

        last_exc: Optional[Exception] = None
        for cand in invoke_candidates:
            if hasattr(session, cand):
                try:
                    method = getattr(session, cand)
                    result = method(tool_name, arguments) if callable(method) else method
                    # If returns awaitable, run it
                    if inspect.isawaitable(result):
                        import asyncio

                        result = asyncio.run(result)
                    return result
                except Exception as exc:
                    last_exc = exc
                    logger.debug("Invocation using %s failed for %s:%s: %s", cand, server_name, tool_name, exc, exc_info=True)

        # If session supports a generic 'request' or 'call_raw' style API, try them
        generic_candidates = ["request", "send", "call_raw"]
        for cand in generic_candidates:
            if hasattr(session, cand):
                try:
                    method = getattr(session, cand)
                    payload = {"tool": tool_name, "args": arguments}
                    result = method(payload)
                    if inspect.isawaitable(result):
                        import asyncio

                        result = asyncio.run(result)
                    return result
                except Exception as exc:
                    last_exc = exc
                    logger.debug("Generic invocation %s failed: %s", cand, exc, exc_info=True)

        # If all attempts failed, raise a descriptive error
        msg = f"Could not invoke tool '{tool_name}' on server '{server_name}'"
        if last_exc:
            raise McpConnectionError(msg + f": {last_exc}") from last_exc
        raise McpConnectionError(msg)

    def disconnect_server(self, name: str) -> None:
        """
        Gracefully shutdown the stdio session and terminate the subprocess.
        Safe to call multiple times.
        """
        with self._global_lock:
            entry = self._servers.get(name)
            if not entry:
                return

            proc: subprocess.Popen = entry.get("proc")
            cmgr = entry.get("cmgr")
            client = entry.get("client")

            # Attempt to close session/context manager if present
            try:
                if cmgr is not None:
                    # Call __exit__ on the context manager to close underlying resources
                    cmgr.__exit__(None, None, None)  # type: ignore[attr-defined]
            except Exception:
                logger.exception("Error while exiting stdio_client context for %s", name)

            # Terminate process if still running
            try:
                if proc and proc.poll() is None:
                    proc.terminate()
                    # give it a short grace period
                    try:
                        proc.wait(timeout=2.0)
                    except Exception:
                        proc.kill()
            except Exception:
                logger.exception("Error while terminating MCP subprocess for %s", name)

            # Remove from registry
            try:
                del self._servers[name]
            except KeyError:
                pass

    def shutdown(self) -> None:
        """Shutdown all known servers."""
        with self._global_lock:
            names = list(self._servers.keys())
        for n in names:
            try:
                self.disconnect_server(n)
            except Exception:
                logger.exception("Error disconnecting MCP server %s", n)


# Basic module-level helper: a global manager instance
_global_mcp_manager: Optional[McpManager] = None


def get_global_manager() -> McpManager:
    global _global_mcp_manager
    if _global_mcp_manager is None:
        _global_mcp_manager = McpManager()
    return _global_mcp_manager