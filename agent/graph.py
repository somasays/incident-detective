"""Actual StateGraph orchestration, controlled exits and conditional validation routing."""

import config  # noqa: F401 -- disable inherited tracing before importing LangGraph

# isort: split
from langgraph.graph import END, START, StateGraph

from agent.nodes import InvestigationNodes
from agent.state import InvestigationState


def build_investigator(repository, reasoner):
    nodes = InvestigationNodes(repository, reasoner)
    builder = StateGraph(InvestigationState)
    names = (
        "load_incident",
        "traverse_dependencies",
        "collect_evidence",
        "analyze_evidence",
        "validate_hypotheses",
        "finalize",
        "fallback",
    )
    for name in names:
        builder.add_node(name, getattr(nodes, name))
    builder.add_edge(START, "load_incident")
    for source, destination in (
        ("load_incident", "traverse_dependencies"),
        ("traverse_dependencies", "collect_evidence"),
        ("collect_evidence", "analyze_evidence"),
    ):
        builder.add_conditional_edges(
            source,
            lambda s: "error" if s.get("retrieval_error") else "ok",
            {"ok": destination, "error": "fallback"},
        )
    builder.add_edge("analyze_evidence", "validate_hypotheses")
    builder.add_conditional_edges(
        "validate_hypotheses",
        lambda s: (
            "valid" if s.get("analysis_available") and not s.get("validation_error") else "invalid"
        ),
        {"valid": "finalize", "invalid": "fallback"},
    )
    builder.add_edge("finalize", END)
    builder.add_edge("fallback", END)
    return builder.compile()
