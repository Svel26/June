"""Drafter node: generate tool calls using LLM; does not execute tools."""
from typing import Any, List, Dict
import json
from langchain_core.messages import HumanMessage, AIMessage
from llm import get_llm
from state import AgentState

def drafter_node(state: AgentState) -> AgentState:
    """
    Produce drafted tool calls for the current plan step using the LLM.

    The node should NOT execute any tools. It attaches a structured list of
    tool call dicts to state["tool_calls"] and appends an AIMessage containing
    the drafted tool calls (JSON).
    """
    # Ensure messages and tool_calls exist
    if "messages" not in state or state["messages"] is None:
        state["messages"] = []
    if "tool_calls" not in state:
        state["tool_calls"] = []

    llm = get_llm("coding")

    idx = int(state.get("current_step_index", 0))
    plan = state.get("plan")
    step = ""
    if plan is not None and hasattr(plan, "steps"):
        try:
            step = plan.steps[idx]
        except Exception:
            step = ""

    prompt = HumanMessage(content=(
        "Draft a sequence of tool calls (JSON only) that, when executed, will "
        f"accomplish the following specific step:\n\n{step}\n\n"
        "Return a JSON object with a single key 'tool_calls' whose value is a list "
        "of calls. Each call must be an object with 'name' (the tool name) and "
        "'args' (an object of named arguments). Only return the JSON object, no extra text."
    ))

    messages = state.get("messages", [])
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
        response = AIMessage(content='{"tool_calls": []}')

    content = getattr(response, "content", str(response))
    # Try to parse the drafted tool calls from the LLM response
    tool_calls: List[Dict] = []
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "tool_calls" in parsed and isinstance(parsed["tool_calls"], list):
            tool_calls = parsed["tool_calls"]
        elif isinstance(parsed, list):
            tool_calls = parsed
    except Exception:
        # If parsing fails, leave tool_calls empty; the executor should handle absence
        tool_calls = []

    # Attach drafted tool calls and the response message to the state
    state["tool_calls"] = tool_calls
    messages.append(AIMessage(content=content))
    state["messages"] = messages

    return state