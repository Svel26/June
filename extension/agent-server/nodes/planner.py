"""Planner node: generate step-by-step plan using LLM and attach to AgentState."""
from typing import List
import json
import re
from pydantic import BaseModel
from langchain_core.messages import SystemMessage, AIMessage
from llm import get_llm
from state import AgentState
from utils.repo_map import generate_repo_map
from prompts import planner_system_message


class Plan(BaseModel):
    steps: List[str]


def planner_node(state: AgentState) -> AgentState:
    """
    Call the LLM with a system prompt to produce a Plan and attach it to the state.
    The repository map is regenerated on every planning turn and appended to the system prompt
    so the LLM has up-to-date context about the project structure.
    """
    # generate fresh repo map for this planning turn
    repo_map = generate_repo_map(".")

    llm = get_llm("reasoning")
    system = planner_system_message(repo_map)
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
 
    # capture thought process (prefer <think>...</think>, fallback to first message chunk)
    thought = ""
    try:
        m = re.search(r"<think>(.*?)</think>", content, re.S)
        if m:
            thought = m.group(1).strip()
        else:
            # fallback to first non-empty paragraph/chunk
            chunks = [c.strip() for c in content.split("\n\n") if c.strip()]
            thought = chunks[0] if chunks else content.strip()
    except Exception:
        thought = content.strip()
    state["thought_trace"] = thought

    # record which model was used for reasoning
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

    # update messages and attach plan
    state["messages"].append(AIMessage(content=content))
    state["plan"] = plan
    return state