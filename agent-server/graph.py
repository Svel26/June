from typing import TypedDict, List, Callable, Any, Dict
from langchain_core.messages import BaseMessage, AIMessage
from llm import get_llm
from nodes.planner import planner_node
from nodes.executor import executor_node
from schema import Artifact

class AgentState(TypedDict):
    messages: List[BaseMessage]
    plan: List[str]
    artifacts: List[Artifact]
    current_step_index: int

def reasoner(state: AgentState) -> AgentState:
    """
    Call the LLM with the current messages and return a new AgentState
    containing the LLM response as the sole message.
    (Kept for backward compatibility / tests)
    """
    llm = get_llm()
    try:
        if hasattr(llm, "generate_messages"):
            result = llm.generate_messages(state["messages"])
            response = result[0] if isinstance(result, (list, tuple)) and result else result
        elif hasattr(llm, "predict_messages"):
            response = llm.predict_messages(state["messages"])
        else:
            response = llm(state["messages"])
    except Exception:
        response = AIMessage(content="llm call failed")

    # Preserve other AgentState fields when returning for backward compatibility
    return {
        "messages": [response],
        "plan": state.get("plan", []),
        "artifacts": state.get("artifacts", []),
        "current_step_index": state.get("current_step_index", 0),
    }

def should_continue(state: AgentState) -> Any:
    """
    Conditional node deciding whether to continue executing plan steps.

    Returns:
    - "executor" to loop back to the executor node (when there are remaining steps)
    - "END" to terminate the graph (when plan is exhausted)
    """
    try:
        idx = int(state.get("current_step_index", 0))
        plan = state.get("plan", [])
        # plan may be a pydantic Plan or a plain list; handle both
        length = 0
        try:
            # If plan is pydantic model with .steps
            if hasattr(plan, "steps"):
                length = len(plan.steps)
            else:
                length = len(plan)
        except Exception:
            length = 0

        if idx < length:
            return "executor"
    except Exception:
        # On any error, stop to avoid infinite loops
        return "END"
    return "END"

class StateGraph:
    def __init__(self, state_type: Any):
        self.state_type = state_type
        self._nodes: Dict[str, Callable[[Any], Any]] = {}
        self._edges: List[tuple[str, str]] = []

    def add_node(self, name: str, func: Callable[[Any], Any]) -> None:
        self._nodes[name] = func

    def add_edge(self, src: str, dst: str) -> None:
        self._edges.append((src, dst))

    def compile(self) -> Callable[[Any], Any]:
        def app(state: Any) -> Any:
            # Ensure defaults for new AgentState fields
            if "messages" not in state:
                state["messages"] = []
            if "plan" not in state:
                state["plan"] = []
            if "artifacts" not in state:
                state["artifacts"] = []
            if "current_step_index" not in state:
                state["current_step_index"] = 0

            current = "START"
            s = state
            # Walk the graph deterministically following the first outgoing edge
            while True:
                outgoing = [dst for (a, dst) in self._edges if a == current]
                if not outgoing:
                    break
                next_node = outgoing[0]
                if next_node == "END":
                    break
                node_fn = self._nodes.get(next_node)
                if node_fn is None:
                    break

                result = node_fn(s)

                # Conditional nodes may return a string indicating the next node
                if isinstance(result, str):
                    if result == "END":
                        break
                    # jump to the returned node name
                    current = result
                    continue

                # Normal nodes return an updated state
                s = result
                # advance along the graph to the node we just executed
                current = next_node
            return s
        return app

# Build and compile the graph with planner/executor flow and a conditional node
graph = StateGraph(AgentState)
graph.add_node("planner", planner_node)
graph.add_node("executor", executor_node)
graph.add_node("conditional_edge", should_continue)
# START -> planner -> executor -> conditional_edge
graph.add_edge("START", "planner")
graph.add_edge("planner", "executor")
graph.add_edge("executor", "conditional_edge")

app = graph.compile()