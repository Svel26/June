from typing import List, Callable, Any, Dict, Optional
from langchain_core.messages import AIMessage
from state import AgentState
from llm import get_llm
from nodes.planner import planner_node
from nodes.drafter import drafter_node
from nodes.executor import executor_node
from nodes.reflector import reflector_node
from schema import Artifact

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

    Behavior:
    - If there are approved/executed tool outputs with errors, return "planner"
      so the planner can observe tool outputs and replan (self-correction).
    - Otherwise, if there are remaining plan steps, return "executor" to continue.
    - Return "END" when the plan is exhausted or on fatal errors.
    """
    try:
        # First, inspect the most recent messages for tool outputs/errors so planner
        # or executor can react to tool failures and retry/replan as needed.
        msgs = state.get("messages", []) or []
        # Explicit error flag takes precedence: route to reflector for self-correction
        if state.get("error_state"):
            return "reflector"
        if msgs:
            last = msgs[-1]
            content = getattr(last, "content", None)
            if content:
                try:
                    parsed = json.loads(content)
                    # Expecting a list of tool output dicts; if any contains "error",
                    # route back to planner so it can re-evaluate the plan.
                    if isinstance(parsed, list):
                        for item in parsed:
                            if isinstance(item, dict) and ("error" in item or item.get("requires_approval")):
                                # If an error occured or there's a pending approval, go back to planner
                                return "planner"
                except Exception:
                    # If parsing fails, ignore and continue to step-count checks below
                    pass

        idx = int(state.get("current_step_index", 0))
        plan = state.get("plan", [])
        # plan may be a pydantic Plan or a plain list; handle both
        length = 0
        try:
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

    def compile(self, interrupt_before: Optional[List[str]] = None) -> Callable[[Any], Any]:
        """
        Compile the state graph into a callable app(state).
        If interrupt_before is provided, the app will return early (pause) when it
        reaches any node listed in interrupt_before, allowing a human-in-the-loop step
        before the node executes (e.g., before executing tools).
        """
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

                # If configured, pause before executing nodes listed in interrupt_before
                if interrupt_before and next_node in interrupt_before:
                    return s

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

# Build and compile the graph with planner -> drafter -> executor flow and a conditional node
graph = StateGraph(AgentState)
graph.add_node("planner", planner_node)
graph.add_node("drafter", drafter_node)
graph.add_node("executor", executor_node)
graph.add_node("reflector", reflector_node)
graph.add_node("conditional_edge", should_continue)
# START -> planner -> drafter -> executor -> conditional_edge
graph.add_edge("START", "planner")
graph.add_edge("planner", "drafter")
graph.add_edge("drafter", "executor")
graph.add_edge("executor", "conditional_edge")
# After reflecting, immediately retry execution
graph.add_edge("reflector", "executor")
 
# Pause before 'executor' so a human-in-the-loop can review/approve drafted tool calls
app = graph.compile(interrupt_before=["executor"])