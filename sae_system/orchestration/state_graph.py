"""LangGraph StateGraph wiring all SAE nodes and conditional edges."""

import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

from orchestration.state_schema import GraphState
from agents.tutor_agent import TutorAgent
from agents.auditor_agent import AuditorAgent
from agents.searcher_agent import SearcherAgent
from memory.graph_engine import KnowledgeGraph

load_dotenv()

SEMANTIC_PASS_THRESHOLD = float(os.getenv("SEMANTIC_PASS_THRESHOLD", "0.85"))
SEMANTIC_DIALOGUE_THRESHOLD = float(os.getenv("SEMANTIC_DIALOGUE_THRESHOLD", "0.60"))

_tutor = TutorAgent()
_auditor = AuditorAgent()
_searcher = SearcherAgent()
_knowledge_graph = KnowledgeGraph()


def lesson_node(state: GraphState) -> GraphState:
    """Run the tutor agent to generate lesson content."""
    return _tutor.run(state)


def auditor_node(state: GraphState) -> GraphState:
    """Run the auditor agent to score the student response."""
    return _auditor.run(state)


def clarification_dialogue_node(state: GraphState) -> GraphState:
    """Present a Socratic probe and re-evaluate the student's clarification."""
    from evaluation.semantic_auditor import generate_socratic_probe, evaluate_clarification

    probe = generate_socratic_probe(state["concept_id"], state["student_response"])
    print(f"\n[Socratic Probe] {probe}")

    clarification = state.get("student_response", "")
    new_score = evaluate_clarification(clarification, state.get("reference_answer", ""))
    new_score = max(0.0, min(1.0, new_score))

    state["semantic_score"] = new_score
    composite = (new_score * 0.7) + (state.get("logic_score", 0.0) * 0.3)
    composite = max(0.0, min(1.0, composite))
    state["composite_score"] = composite

    if composite >= SEMANTIC_PASS_THRESHOLD:
        state["current_phase"] = "complete"
    else:
        state["current_phase"] = "retry"
    return state


def retry_with_hint_node(state: GraphState) -> GraphState:
    """Append a retrieval hint to lesson content before re-running the tutor."""
    state["current_phase"] = "retry"
    return state


def next_lesson_node(state: GraphState) -> GraphState:
    """Advance to the next recommended concept or mark session complete."""
    recommended = _knowledge_graph.get_next_recommended_nodes(state["concept_id"])
    if recommended:
        state["next_concept_id"] = recommended[0]
        state["concept_id"] = recommended[0]
        state["current_phase"] = "lesson"
        state["lesson_content"] = ""
        state["student_response"] = ""
        state["reference_answer"] = ""
    else:
        state["current_phase"] = "complete"
        state["next_concept_id"] = ""
    return state


def _route_after_audit(state: GraphState) -> str:
    """Conditional router: decide next node based on composite_score."""
    score = state.get("composite_score", 0.0)
    if score >= SEMANTIC_PASS_THRESHOLD:
        return "next_lesson"
    elif score >= SEMANTIC_DIALOGUE_THRESHOLD:
        return "clarification"
    else:
        return "retry"


def _route_after_clarification(state: GraphState) -> str:
    """Conditional router after clarification dialogue."""
    if state.get("current_phase") == "complete":
        return "next_lesson"
    return "retry"


def _route_after_next_lesson(state: GraphState) -> str:
    """Conditional router: end if no more concepts, else continue tutoring."""
    if state.get("current_phase") == "complete" or not state.get("next_concept_id"):
        return "end"
    return "tutor"


def build_graph() -> StateGraph:
    """Assemble and compile the SAE LangGraph StateGraph."""
    builder = StateGraph(GraphState)

    builder.add_node("tutor", lesson_node)
    builder.add_node("auditor", auditor_node)
    builder.add_node("clarification", clarification_dialogue_node)
    builder.add_node("retry", retry_with_hint_node)
    builder.add_node("searcher", _searcher.run)
    builder.add_node("next_lesson", next_lesson_node)

    builder.set_entry_point("tutor")

    builder.add_edge("tutor", "auditor")

    builder.add_conditional_edges(
        "auditor",
        _route_after_audit,
        {
            "next_lesson": "next_lesson",
            "clarification": "clarification",
            "retry": "retry",
        },
    )

    builder.add_conditional_edges(
        "clarification",
        _route_after_clarification,
        {
            "next_lesson": "next_lesson",
            "retry": "retry",
        },
    )

    builder.add_edge("retry", "searcher")
    builder.add_edge("searcher", "tutor")

    builder.add_conditional_edges(
        "next_lesson",
        _route_after_next_lesson,
        {
            "end": END,
            "tutor": "tutor",
        },
    )

    return builder.compile()


sae_graph = build_graph()
