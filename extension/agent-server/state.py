from typing import TypedDict, List
from langchain_core.messages import BaseMessage
from schema import Artifact

class AgentState(TypedDict):
    messages: List[BaseMessage]
    plan: List[str]
    artifacts: List[Artifact]
    current_step_index: int
    thought_trace: str
    active_model: str