from fastapi import FastAPI, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from graph import app as graph_app, graph as state_graph
from llm import get_llm
from store import create_task, update_task_state, get_task
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

@app.get("/task/{task_id}")
def get_task_endpoint(task_id: str):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)