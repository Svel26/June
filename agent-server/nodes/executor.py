"""Executor node: execute drafted tool calls using the available tool functions."""
from typing import Any, List, Dict
from langchain_core.messages import ToolMessage, AIMessage
# Optional StructuredTool import for LangChain integration
try:
    from langchain.tools import StructuredTool
except Exception:
    StructuredTool = None
from state import AgentState
from llm import get_llm
from config import get_settings
from mcp_client import get_global_manager
from tools import fs, terminal, search
from schema import Artifact
import uuid
import json

def _is_error_output(name: str, output: Any) -> bool:
    """Heuristic to detect error outcomes returned as strings by some tools."""
    if output is None:
        return False
    if name == "run_command" and isinstance(output, str):
        # terminal.run_command returns user-friendly error messages as strings.
        lowered = output.lower()
        if "command failed" in lowered or "timed out" in lowered or "failed to start background process" in lowered:
            return True
    return False

def executor_node(state: AgentState) -> AgentState:
    """
    Execute drafted tool calls attached to the state (state['tool_calls'] or
    encoded in the last AIMessage). This node runs the tools (fs.* and terminal.run_command)
    and appends a ToolMessage containing the outputs. It also creates Artifact objects for
    any write_file calls.

    NOTE: Shell commands (tool name 'run_command') must NOT be executed directly.
    Instead, they are recorded as pending approvals (HITL) so a human may approve
    execution. This function binds the terminal.run_command tool to the available
    tool registry but defers execution until approval.
    """
    # Acquire a coding-capability LLM instance (routing through universal factory)
    llm = get_llm("coding")
    
    # Initialize MCP manager from configuration and attempt to connect configured servers.
    # Settings may provide MCP_SERVERS as a dict or list. This is best-effort and
    # must not raise on failure.
    settings = get_settings()
    mcp_config = getattr(settings, "MCP_SERVERS", None)
    mcp_mgr = None
    try:
        mcp_mgr = get_global_manager()
        if mcp_config:
            # support dict form: { name: { "command": "...", "args": [...] } }
            if isinstance(mcp_config, dict):
                for sname, cfg in mcp_config.items():
                    try:
                        if isinstance(cfg, str):
                            cmd = cfg
                            args = []
                        elif isinstance(cfg, list):
                            cmd = cfg[0] if cfg else ""
                            args = cfg[1:] if len(cfg) > 1 else []
                        elif isinstance(cfg, dict):
                            cmd = cfg.get("command") or cfg.get("cmd") or ""
                            args = cfg.get("args") or []
                        else:
                            continue
                        if cmd:
                            try:
                                mcp_mgr.connect_to_server(sname, cmd, args)
                            except Exception:
                                # best-effort; continue on failure
                                pass
                    except Exception:
                        continue
            # support list form: [ { "name": "...", "command": "...", "args": [...] }, ... ]
            elif isinstance(mcp_config, list):
                for entry in mcp_config:
                    try:
                        if not isinstance(entry, dict):
                            continue
                        name = entry.get("name")
                        cmd = entry.get("command") or entry.get("cmd") or ""
                        args = entry.get("args") or []
                        if name and cmd:
                            try:
                                mcp_mgr.connect_to_server(name, cmd, args)
                            except Exception:
                                pass
                    except Exception:
                        continue
    except Exception:
        mcp_mgr = None
    
    # Ensure artifacts and pending approvals list exist on state
    if "artifacts" not in state or state["artifacts"] is None:
        state["artifacts"] = []
    if "pending_approvals" not in state or state["pending_approvals"] is None:
        state["pending_approvals"] = []
    
    # Track retry count and error state
    retry_count = int(state.get("retry_count", 0) or 0)
    error_state = bool(state.get("error_state", False))
    had_error = False
    
    # Tool registry mapping expected internal tool names to callable functions
    tool_map = {
        "list_files": fs.list_files,
        "read_file": fs.read_file,
        "write_file": fs.write_file,
        "run_command": terminal.run_command,
        "search_code": search.search_code,
    }
    
    # Convert internal tools and discovered MCP tools into a combined list consumable by agents.
    combined_tools: List[Any] = []
    try:
        # Prefer LangChain StructuredTool when available for better integration.
        if StructuredTool is not None:
            for tname, func in tool_map.items():
                try:
                    st = StructuredTool.from_function(func, name=tname, description=(func.__doc__ or ""))
                    combined_tools.append(st)
                except Exception:
                    combined_tools.append({"name": tname, "func": func})
        else:
            for tname, func in tool_map.items():
                combined_tools.append({"name": tname, "func": func})
    except Exception:
        # Fall back to simple mapping on any unexpected error
        combined_tools = [{"name": k, "func": v} for k, v in tool_map.items()]
    
    # Discover external tools from MCP manager and wrap them as callables / StructuredTool
    if mcp_mgr is not None:
        try:
            external = mcp_mgr.list_tools() or {}
            for server_name, server_tools in external.items():
                if not isinstance(server_tools, dict):
                    continue
                for tool_key, meta in server_tools.items():
                    full_name = f"{server_name}:{tool_key}"
    
                    # create a closure that routes calls to the MCP manager
                    def _make_call(srv: str, tkey: str):
                        def _call(*args, **kwargs):
                            # Prefer kwargs dict as the named arguments payload
                            try:
                                if kwargs:
                                    return mcp_mgr.call_tool(f"{srv}:{tkey}", kwargs)
                                if len(args) == 1 and isinstance(args[0], dict):
                                    return mcp_mgr.call_tool(f"{srv}:{tkey}", args[0])
                                # otherwise pass positional args as a list under "args"
                                return mcp_mgr.call_tool(f"{srv}:{tkey}", {"args": list(args)})
                            except Exception as e:
                                raise
                        return _call
    
                    call_fn = _make_call(server_name, tool_key)
                    desc = ""
                    try:
                        if isinstance(meta, dict):
                            desc = meta.get("description") or meta.get("doc") or ""
                    except Exception:
                        desc = ""
    
                    if StructuredTool is not None:
                        try:
                            st = StructuredTool.from_function(call_fn, name=full_name, description=desc or "")
                            combined_tools.append(st)
                        except Exception:
                            combined_tools.append({"name": full_name, "func": call_fn})
                    else:
                        combined_tools.append({"name": full_name, "func": call_fn})
        except Exception:
            # discovery is best-effort; ignore failures
            pass
    
    # Attach combined tools to the LLM instance so downstream agent orchestration can access them.
    try:
        setattr(llm, "tools", combined_tools)
    except Exception:
        # best-effort, non-fatal
        pass

    # Obtain drafted tool calls from explicit state entry, else try parsing last message
    tool_calls: List[Dict] = state.get("tool_calls") or []
    if not tool_calls:
        try:
            last = state.get("messages", [])[-1]
            content = getattr(last, "content", str(last))
            parsed = json.loads(content)
            if isinstance(parsed, dict) and "tool_calls" in parsed:
                tool_calls = parsed["tool_calls"]
            elif isinstance(parsed, list):
                tool_calls = parsed
            else:
                tool_calls = []
        except Exception:
            tool_calls = []

    outputs: List[Dict] = []

    for call in tool_calls:
        name = call.get("name") or call.get("tool")
        args = call.get("args", {}) or {}
        try:
            func = tool_map.get(name)
            if func is None:
                raise ValueError(f"Unknown tool: {name}")

            # Special handling: defer execution of shell commands for HITL approval
            if name == "run_command":
                # Create a pending approval entry instead of executing
                approval_id = uuid.uuid4().hex
                pending = state.get("pending_approvals", [])
                pending_entry = {
                    "id": approval_id,
                    "type": "run_command",
                    "args": args,
                    "status": "pending_approval",
                }
                pending.append(pending_entry)
                state["pending_approvals"] = pending

                outputs.append({
                    "name": name,
                    "requires_approval": True,
                    "approval_id": approval_id,
                    "args": args,
                    "note": "HITL required: shell commands are not executed automatically."
                })
                # Do not execute the terminal.run_command here
                continue

            # Support dict kwargs or positional list args for other tools
            if isinstance(args, dict):
                out = func(**args)
            elif isinstance(args, list):
                out = func(*args)
            else:
                out = func(args)

            # Detect error-like outputs returned as strings (heuristic)
            if _is_error_output(name, out):
                had_error = True
                retry_count += 1
                state["error_state"] = True
                outputs.append({"name": name, "output": out, "error": "detected_error"})
                # If retry limit exceeded, create an escalation HITL entry and stop processing further tools.
                if retry_count > 3:
                    escalation = {
                        "id": uuid.uuid4().hex,
                        "type": "escalation",
                        "reason": "retry_limit_exceeded",
                        "status": "pending_human",
                        "details": {"tool": name, "output": out},
                    }
                    pending = state.get("pending_approvals", [])
                    pending.append(escalation)
                    state["pending_approvals"] = pending
                    state["halted"] = True
                break

            outputs.append({"name": name, "output": out})

            # Create artifact for write_file calls when possible
            if name == "write_file":
                try:
                    path = args.get("path") if isinstance(args, dict) else None
                    content = args.get("content") if isinstance(args, dict) else None
                    title = path or f"generated_code_{uuid.uuid4().hex[:8]}.txt"
                    art = Artifact(id=uuid.uuid4(), type="code", title=title, content=content or "")
                    state_artifacts = state.get("artifacts", [])
                    state_artifacts.append(art)
                    state["artifacts"] = state_artifacts
                except Exception:
                    pass
        except Exception as e:
            # Detect explicit exceptions (file not found, validation errors, etc.)
            had_error = True
            retry_count += 1
            state["error_state"] = True
            outputs.append({"name": name, "error": str(e)})

            # If retry limit exceeded, escalate to human
            if retry_count > 3:
                escalation = {
                    "id": uuid.uuid4().hex,
                    "type": "escalation",
                    "reason": "retry_limit_exceeded",
                    "status": "pending_human",
                    "details": {"tool": name, "error": str(e)},
                }
                pending = state.get("pending_approvals", [])
                pending.append(escalation)
                state["pending_approvals"] = pending
                state["halted"] = True
            # Stop processing further tool calls on error
            break

    # Append a ToolMessage (fallback to AIMessage if ToolMessage construction fails)
    try:
        tool_msg = ToolMessage(content=json.dumps(outputs))
    except Exception:
        tool_msg = AIMessage(content=json.dumps(outputs))

    messages = state.get("messages", [])
    messages.append(tool_msg)
    state["messages"] = messages

    # Process any pending approvals that have been approved by a human.
    # Execute approved run_command entries, capture output/errors and append them
    # to the message history so planner/executor can observe results and retry.
    pending = state.get("pending_approvals", []) or []
    executed_results: List[Dict] = []
    for p in pending:
        try:
            # Only execute approvals that were explicitly approved and not yet executed
            if p.get("type") == "run_command" and p.get("status") == "approved" and not p.get("executed"):
                p_args = p.get("args", {}) or {}
                try:
                    # Call terminal.run_command using dict kwargs or positional list
                    if isinstance(p_args, dict):
                        result = terminal.run_command(**p_args)
                    elif isinstance(p_args, list):
                        result = terminal.run_command(*p_args)
                    else:
                        result = terminal.run_command(p_args)
                    # Detect error-like outputs returned as strings
                    if _is_error_output("run_command", result):
                        had_error = True
                        retry_count += 1
                        state["error_state"] = True
                        executed_results.append({
                            "name": "run_command",
                            "approval_id": p.get("id"),
                            "output": result,
                            "error": "detected_error"
                        })
                        p["status"] = "executed"
                        p["result"] = result
                        p["executed"] = True

                        if retry_count > 3:
                            escalation = {
                                "id": uuid.uuid4().hex,
                                "type": "escalation",
                                "reason": "retry_limit_exceeded",
                                "status": "pending_human",
                                "details": {"approval_id": p.get("id"), "output": result},
                            }
                            pending.append(escalation)
                            state["pending_approvals"] = pending
                            state["halted"] = True
                            # Do not continue executing other approvals after escalation
                            break
                        # continue processing other approvals unless escalation occurred
                    else:
                        executed_results.append({
                            "name": "run_command",
                            "approval_id": p.get("id"),
                            "output": result
                        })
                        p["status"] = "executed"
                        p["result"] = result
                        p["executed"] = True
                except Exception as e:
                    had_error = True
                    retry_count += 1
                    state["error_state"] = True
                    executed_results.append({
                        "name": "run_command",
                        "approval_id": p.get("id"),
                        "error": str(e)
                    })
                    p["status"] = "executed"
                    p["error"] = str(e)
                    p["executed"] = True

                    if retry_count > 3:
                        escalation = {
                            "id": uuid.uuid4().hex,
                            "type": "escalation",
                            "reason": "retry_limit_exceeded",
                            "status": "pending_human",
                            "details": {"approval_id": p.get("id"), "error": str(e)},
                        }
                        pending.append(escalation)
                        state["pending_approvals"] = pending
                        state["halted"] = True
                        break
        except Exception:
            # Be resilient: on any issue processing a pending approval, attach an error entry
            had_error = True
            retry_count += 1
            state["error_state"] = True
            executed_results.append({
                "name": "run_command",
                "approval_id": p.get("id"),
                "error": "failed to process pending approval"
            })
            p["status"] = "executed"
            p["error"] = "failed to process pending approval"
            p["executed"] = True

            if retry_count > 3:
                escalation = {
                    "id": uuid.uuid4().hex,
                    "type": "escalation",
                    "reason": "retry_limit_exceeded",
                    "status": "pending_human",
                    "details": {"approval_id": p.get("id"), "error": "failed to process pending approval"},
                }
                pending.append(escalation)
                state["pending_approvals"] = pending
                state["halted"] = True
                break

    # If we executed any approvals, append their outputs as a new ToolMessage so the
    # planner and executor nodes can observe the results and react (retry/replan).
    if executed_results:
        try:
            exec_msg = ToolMessage(content=json.dumps(executed_results))
        except Exception:
            exec_msg = AIMessage(content=json.dumps(executed_results))
        messages = state.get("messages", [])
        messages.append(exec_msg)
        state["messages"] = messages

    # Persist updated pending approvals back to state
    state["pending_approvals"] = pending

    # Persist retry_count and error_state back to state
    state["retry_count"] = retry_count
    state["error_state"] = state.get("error_state", False) or had_error

    # Advance the step index (executor finishes the drafted step) only if no error occurred
    if not had_error and not state.get("halted", False):
        idx = int(state.get("current_step_index", 0))
        state["current_step_index"] = idx + 1
    else:
        # Do not advance current_step_index on error; leave index as-is for retry or HITL.
        state["current_step_index"] = int(state.get("current_step_index", 0))

    # Ensure artifacts and pending approvals persisted in the state
    state["artifacts"] = state.get("artifacts", [])
    state["pending_approvals"] = state.get("pending_approvals", [])

    return state