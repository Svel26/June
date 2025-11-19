"""Planner node: generate step-by-step plan using LLM and attach to AgentState."""
from typing import List
import json
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, AIMessage
from llm import get_llm
from graph import AgentState


class Plan(BaseModel):
    steps: List[str]


def planner_node(state: AgentState) -> AgentState:
    """
    Call the LLM with a system prompt to produce a Plan and attach it to the state.
    """
    llm = get_llm()
    system = SystemMessage(content="You are a coding architect. Break the user request into a step-by-step plan.")
    messages = [system] + state.get("messages", [])

    try:
        structured = llm.with_structured_output(Plan)
        if hasattr(structured, "generate_messages"):
            result = structured.generate_messages(messages)
            response = result[0] if isinstance(result, (list, tuple)) and result else result
        elif hasattr(structured, "predict_messages"):
            response = structured.predict_messages(messages)
        else:
            response = structured(messages)
    except Exception:
        response = AIMessage(content='{"steps": []}')

    content = getattr(response, "content", str(response))
    try:
        plan = Plan.parse_raw(content)
    except Exception:
        try:
            plan = Plan(**json.loads(content))
        except Exception:
            plan = Plan(steps=[])

    # update messages and attach plan
    state["messages"].append(AIMessage(content=content))
    state["plan"] = plan
    return state