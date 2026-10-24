"""Evidence-only LangGraph retrieval with a bounded, explicit error route."""

import hashlib
import json
from time import perf_counter
from typing import TypedDict

import config  # noqa: F401 -- disable inherited tracing before importing LangGraph

# isort: split
from langgraph.graph import END, START, StateGraph

from knowledge.temporal_queries import resolve_request


class EvidenceState(TypedDict, total=False):
    question: str
    options: dict
    request: dict
    topology: dict
    package: dict
    stages: list[dict]
    error: str


def build_evidence_workflow(repository):
    """Retrieve and package graph evidence without any model or no-op analysis nodes."""

    def resolve(state):
        return {
            "request": resolve_request(
                state["question"], repository.catalog(), **state.get("options", {})
            )
        }

    def topology(state):
        return {"topology": repository.topology(state["request"])}

    def evidence(state):
        return {"package": repository.collect(state["request"], state["topology"])}

    def finalize(state):
        package = {
            **state["package"],
            "analysis": {},
            "analysisAvailable": False,
            "status": "evidence_only",
            "stages": state["stages"],
        }
        package["investigationId"] = hashlib.sha256(
            json.dumps(package, sort_keys=True).encode()
        ).hexdigest()[:16]
        return {"package": package}

    def fallback(state):
        return {
            "package": {
                **state.get("package", {}),
                "analysis": {},
                "analysisAvailable": False,
                "status": "unavailable",
                "error": state["error"],
                "stages": state.get("stages", []),
            }
        }

    steps = [
        ("resolve_question", resolve, "Retrieve the known service/system and resolve time"),
        ("reconstruct_topology", topology, "Traverse the topology valid at the selected time"),
        ("collect_temporal_evidence", evidence, "Compare state, measurements, changes and code"),
        ("finalize", finalize, "Package the exact retrieved evidence"),
    ]
    builder = StateGraph(EvidenceState)
    for index, (name, function, purpose) in enumerate(steps):

        def instrument(state, function=function, name=name, purpose=purpose, index=index):
            started = perf_counter()
            try:
                update = function(state)
            except Exception as exc:
                update = {"error": f"{type(exc).__name__}: {exc}"[:1000]}
            record = {
                "stage": name,
                "purpose": purpose,
                "elapsedMs": round((perf_counter() - started) * 1000),
                "status": "failed" if update.get("error") else "complete",
                "next": "fallback"
                if update.get("error")
                else (steps[index + 1][0] if index + 1 < len(steps) else "END"),
            }
            stages = [*state.get("stages", []), record]
            if name == "finalize" and "package" in update:
                update["package"]["stages"] = stages
            return {**update, "stages": stages}

        builder.add_node(name, instrument)
    builder.add_node("fallback", fallback)
    builder.add_edge(START, steps[0][0])
    for (name, _, _), (next_name, _, _) in zip(steps, steps[1:], strict=False):
        builder.add_conditional_edges(
            name,
            lambda state: "error" if state.get("error") else "ok",
            {"error": "fallback", "ok": next_name},
        )
    builder.add_edge("finalize", END)
    builder.add_edge("fallback", END)
    return builder.compile()
