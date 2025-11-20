"""Reflector node: analyze tool error outputs and append LLM reasoning."""
from typing import Any
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from llm import get_llm
from state import AgentState
from prompts import reflector_system_message


def reflector_node(state: AgentState) -> AgentState:
    """
    When a tool step fails (state['error_state'] is True), examine the last message
    (typically a ToolMessage/AIMessage with JSON outputs), ask the LLM to analyze the
    error and provide a concrete instruction to fix it. Append the LLM's reasoning
    as an AIMessage to the message history and clear error_state.
    """
    if "messages" not in state or state["messages"] is None:
        state["messages"] = []
    messages = state["messages"]

    last = messages[-1] if messages else None
    last_content = getattr(last, "content", "") if last is not None else ""

    system = reflector_system_message

    user = HumanMessage(content=f"Error output:\n\n{last_content}")

    llm = get_llm("reasoning")
    try:
        msgs = [system, user]
        if hasattr(llm, "generate_messages"):
            result = llm.generate_messages(msgs)
            response = result[0] if isinstance(result, (list, tuple)) and result else result
        elif hasattr(llm, "predict_messages"):
            response = llm.predict_messages(msgs)
        else:
            response = llm(msgs)
    except Exception:
        response = AIMessage(content="LLM call failed: unable to analyze error output automatically.")

    content = getattr(response, "content", str(response))

    # update thought trace with reflection output
    try:
        state["thought_trace"] = content
    except Exception:
        state["thought_trace"] = str(content)

    # record which model was used for reflection
    model_id = None
    for attr in ("model_id", "model_name", "name", "model"):
        try:
            model_id = getattr(llm, attr, None)
        except Exception:
            model_id = None
        if model_id:
            break
    if model_id is None:
        try:
            model_id = str(llm)
        except Exception:
            model_id = "unknown"
    state["active_model"] = model_id

    messages.append(AIMessage(content=content))
    state["messages"] = messages

    # Reset the error flag so planner/executor can proceed after reflection
    state["error_state"] = False

    return state