"""Executor node: execute individual plan steps using LLM and filesystem tools."""
from typing import Any
from langchain_core.messages import HumanMessage, AIMessage
from llm import get_llm
from graph import AgentState
from tools import fs
from osae_ide.agent_server.schema import Artifact
import uuid
import re

def executor_node(state: AgentState) -> AgentState:
    """
    Execute the current step from state['plan'].steps using the LLM.

    Behavior:
    - Determine current step by state.get('current_step_index', 0)
    - Bind filesystem tools to the LLM via .bind_tools()
    - Call the model with prompt: "Execute this specific step: {step}"
    - Append the LLM response to state['messages'] and increment current_step_index
    - Capture artifacts when write_file is used or when the LLM returns code blocks
    """
    # Ensure artifacts list exists on state
    if "artifacts" not in state or state["artifacts"] is None:
        state["artifacts"] = []

    llm = get_llm()

    # Wrap the fs.write_file tool to create Artifact objects when files are written
    try:
        original_write = fs.write_file
        def write_file_wrapper(path: str, content: str) -> str:
            # Call the original write implementation
            result = original_write(path, content)
            try:
                art = Artifact(id=uuid.uuid4(), type="code", title=path, content=content)
                state_artifacts = state.get("artifacts", [])
                state_artifacts.append(art)
                state["artifacts"] = state_artifacts
            except Exception:
                # Swallow errors creating artifacts to avoid breaking tool behavior
                pass
            return result
        # Replace the tool with our wrapper before binding
        fs.write_file = write_file_wrapper
    except Exception:
        # If wrapping fails, continue without the wrapper
        pass

    # Bind fs tools if the LLM supports binding
    try:
        if hasattr(llm, "bind_tools"):
            # Provide the tool callables from the fs module
            llm.bind_tools([fs.list_files, fs.read_file, fs.write_file])
    except Exception:
        # Ignore binding errors; proceed without tools
        pass

    idx = int(state.get("current_step_index", 0))
    plan = state.get("plan")
    step = ""
    if plan is not None and hasattr(plan, "steps"):
        try:
            step = plan.steps[idx]
        except Exception:
            step = ""

    messages = state.get("messages", [])
    prompt = HumanMessage(content=f"Execute this specific step: {step}")
    messages.append(prompt)

    try:
        if hasattr(llm, "generate_messages"):
            result = llm.generate_messages(messages)
            response = result[0] if isinstance(result, (list, tuple)) and result else result
        elif hasattr(llm, "predict_messages"):
            response = llm.predict_messages(messages)
        else:
            response = llm(messages)
    except Exception:
        response = AIMessage(content="llm call failed")

    messages.append(response)

    # If the LLM returned code blocks in its message, extract them and create artifacts.
    try:
        content = getattr(response, "content", "")
        if content:
            # Find fenced code blocks using triple backticks
            code_blocks = re.findall(r"```(?:[\w+-]*\\n)?(.*?)```", content, flags=re.DOTALL)
            # If none found but the message looks like code (heuristic), treat whole content as code
            if not code_blocks and (content.strip().startswith("def ") or content.strip().startswith("class ") or "\n" in content and len(content.splitlines()) > 3):
                code_blocks = [content]
            for i, code in enumerate(code_blocks):
                try:
                    # Use a generated title for code-only responses; this will be the "filename"
                    title = f"generated_code_{uuid.uuid4().hex[:8]}.txt"
                    art = Artifact(id=uuid.uuid4(), type="code", title=title, content=code)
                    state_artifacts = state.get("artifacts", [])
                    state_artifacts.append(art)
                    state["artifacts"] = state_artifacts
                except Exception:
                    pass
    except Exception:
        # Don't allow artifact creation to break the executor
        pass

    state["messages"] = messages
    state["current_step_index"] = idx + 1

    # Ensure the state update includes the artifacts list
    state["artifacts"] = state.get("artifacts", [])

    return state