from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from typing import Optional
from langchain_core.messages import HumanMessage
from graph import app as graph_app, graph as state_graph
from llm import get_llm
from store import create_task, update_task_state, get_task, TASK_STORE
import uuid
import traceback

app = FastAPI()

class TaskRequest(BaseModel):
    prompt: str

@app.get("/health")
def health():
    return {"status": "active", "component": "agent-server"}

@app.post("/task")
def create_task_endpoint(req: TaskRequest, background_tasks: BackgroundTasks):
    try:
        # Verify Ollama is available
        _ = get_llm()
    except ConnectionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama is not running. Please run 'ollama serve'."
        )

    task_id = str(uuid.uuid4())
    create_task(task_id)
    background_tasks.add_task(run_agent_background, task_id, req.prompt)
    return {"task_id": task_id}

def run_agent_background(task_id: str, prompt: str):
    """
    Background worker that runs the agent graph and updates TASK_STORE in real-time.
    """
    try:
        human = HumanMessage(content=prompt)
        state = {"messages": [human]}

        # Ensure task exists and write initial state
        create_task(task_id)
        update_task_state(task_id, {
            "messages": [getattr(m, "content", str(m)) for m in state.get("messages", [])],
            "plan": state.get("plan", []),
            "current_step_index": state.get("current_step_index", 0)
        })

        current = "START"
        s = state
        # Walk the same graph logic as StateGraph.compile to allow streaming updates
        while True:
            outgoing = [dst for (a, dst) in state_graph._edges if a == current]
            if not outgoing:
                break
            next_node = outgoing[0]
            if next_node == "END":
                break
            node_fn = state_graph._nodes.get(next_node)
            if node_fn is None:
                break

            result = node_fn(s)

            # Conditional nodes may return a string indicating the next node
            if isinstance(result, str):
                if result == "END":
                    break
                current = result
                continue

            # Normal nodes return an updated state
            s = result

            # Prepare a serializable snapshot and update the task store
            try:
                messages_serial = [getattr(m, "content", str(m)) for m in s.get("messages", [])]
            except Exception:
                messages_serial = [str(m) for m in s.get("messages", [])]

            update_task_state(task_id, {
                "messages": messages_serial,
                "plan": s.get("plan", []),
                "current_step_index": s.get("current_step_index", 0)
            })

            current = next_node

        # Final update marking completion
        try:
            messages_serial = [getattr(m, "content", str(m)) for m in s.get("messages", [])]
        except Exception:
            messages_serial = [str(m) for m in s.get("messages", [])]

        update_task_state(task_id, {
            "messages": messages_serial,
            "plan": s.get("plan", []),
            "current_step_index": s.get("current_step_index", 0),
            "done": True
        })
    except Exception as e:
        tb = traceback.format_exc()
        update_task_state(task_id, {"error": str(e), "traceback": tb})

class ApprovalRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None

@app.post("/task/{task_id}/approve")
def approve_task_endpoint(task_id: str, req: ApprovalRequest, background_tasks: BackgroundTasks):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    state = task.get("state") or {}
    # Reconstruct a runnable AgentState: stored messages are serialized strings, rebuild as HumanMessage
    msgs = state.get("messages", []) or []
    s = {
        "messages": [HumanMessage(content=m) for m in msgs],
        "plan": state.get("plan", []),
        "current_step_index": state.get("current_step_index", 0),
        "artifacts": state.get("artifacts", []),
    }

    if req.approved:
        # Resume the graph to completion (no interrupt_before) using StateGraph.compile semantics.
        def _resume(task_id_inner: str, s_inner: dict):
            try:
                # Compile an app with no interrupts so execution continues through executor
                resumed_app = state_graph.compile(interrupt_before=None)
                new_state = resumed_app(s_inner)

                # Serialize messages
                try:
                    messages_serial = [getattr(m, "content", str(m)) for m in new_state.get("messages", [])]
                except Exception:
                    messages_serial = [str(m) for m in new_state.get("messages", [])]

                # Serialize artifacts if present
                arts = []
                for a in new_state.get("artifacts", []) or []:
                    try:
                        arts.append(a.dict())
                    except Exception:
                        arts.append(str(a))

                update_task_state(task_id_inner, {
                    "messages": messages_serial,
                    "plan": new_state.get("plan", []),
                    "current_step_index": new_state.get("current_step_index", 0),
                    "artifacts": arts,
                    "done": True
                })
            except Exception as e:
                tb = traceback.format_exc()
                update_task_state(task_id_inner, {"error": str(e), "traceback": tb})

        background_tasks.add_task(_resume, task_id, s)
        return {"status": "resuming"}

    else:
        # Inject human feedback and route back to drafter
        feedback_text = req.feedback or ""
        s["messages"].append(HumanMessage(content=feedback_text))

        # Import drafter_node lazily to avoid circular import issues
        try:
            from nodes.drafter import drafter_node
            new_s = drafter_node(s)
            try:
                messages_serial = [getattr(m, "content", str(m)) for m in new_s.get("messages", [])]
            except Exception:
                messages_serial = [str(m) for m in new_s.get("messages", [])]

            update_task_state(task_id, {
                "messages": messages_serial,
                "plan": new_s.get("plan", []),
                "current_step_index": new_s.get("current_step_index", 0),
                "tool_calls": new_s.get("tool_calls", []),
            })
        except Exception as e:
            tb = traceback.format_exc()
            update_task_state(task_id, {"error": str(e), "traceback": tb})

        # Inform UI that the next step expected is executor (i.e., await approval)
        return {"status": "rejected", "next": ["executor"]}

@app.get("/task/{task_id}")
def get_task_endpoint(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    state = task.get("state") or {}
    next_nodes = []

    # If task completed, no next nodes
    if state.get("done"):
        next_nodes = []
    else:
        # If explicit 'tool_calls' present on state, we are waiting to run them => executor
        if state.get("tool_calls"):
            next_nodes = ["executor"]
        else:
            # Try to detect drafted tool_calls encoded in the last message
            msgs = state.get("messages", []) or []
            if msgs:
                last = msgs[-1]
                try:
                    import json as _json
                    parsed = _json.loads(last)
                    if isinstance(parsed, dict) and "tool_calls" in parsed:
                        next_nodes = ["executor"]
                    else:
                        # Fallback: if there are remaining plan steps, next is drafter
                        plan = state.get("plan") or []
                        idx = int(state.get("current_step_index", 0))
                        try:
                            length = len(plan)
                        except Exception:
                            length = len(getattr(plan, "steps", []) if hasattr(plan, "steps") else [])
                        if idx < length:
                            next_nodes = ["drafter"]
                except Exception:
                    plan = state.get("plan") or []
                    idx = int(state.get("current_step_index", 0))
                    try:
                        length = len(plan)
                    except Exception:
                        length = len(getattr(plan, "steps", []) if hasattr(plan, "steps") else [])
                    if idx < length:
                        next_nodes = ["drafter"]
            else:
                # No messages yet; if plan has steps, drafter will be next
                plan = state.get("plan") or []
                idx = int(state.get("current_step_index", 0))
                try:
                    length = len(plan)
                except Exception:
                    length = len(getattr(plan, "steps", []) if hasattr(plan, "steps") else [])
                if idx < length:
                    next_nodes = ["drafter"]

    resp = dict(task)
    resp["next"] = next_nodes
    return resp

@app.post("/reset")
def reset_endpoint():
    """Clear the in-memory TASK_STORE."""
    TASK_STORE.clear()
    return {"status": "ok", "message": "TASK_STORE cleared"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)