"""Each method is a LangGraph node returning a serializable state update."""

from agent.reasoning import validate_analysis
from knowledge.bounds import notices
from knowledge.evidence import build_evidence, graph_entity_ids


def stage(state, name, **updates):
    return {"stages": [*state.get("stages", []), name], **updates}


class InvestigationNodes:
    def __init__(self, repository, reasoner):
        self.repository = repository
        self.reasoner = reasoner

    def load_incident(self, state):
        try:
            incident = self.repository.get_incident(state["incident_id"])
            if not incident:
                return stage(
                    state,
                    "load_incident",
                    status="not_found",
                    retrieval_error="Incident not found in the local demo namespace.",
                )
            return stage(
                state,
                "load_incident",
                incident=incident,
                status="retrieving",
                analysis_available=False,
                retrieval_error=None,
                validation_error=None,
            )
        except Exception as exc:
            return stage(
                state,
                "load_incident",
                status="retrieval_failed",
                retrieval_error=f"Local Neo4j retrieval failed ({type(exc).__name__}).",
            )

    def traverse_dependencies(self, state):
        try:
            rows = self.repository.dependencies(state["incident_id"])
            if not rows:
                raise ValueError("No affected component path retrieved")
            paths = sorted({tuple(r["path"]) for r in rows})
            component_ids = sorted({id for p in paths for id in p})
            return stage(
                state,
                "traverse_dependencies",
                dependency_paths=[list(p) for p in paths],
                component_ids=component_ids,
                traversal_truncated=any(r.get("truncated") for r in rows),
            )
        except Exception as exc:
            return stage(
                state,
                "traverse_dependencies",
                status="retrieval_failed",
                retrieval_error=f"Dependency retrieval failed ({type(exc).__name__}).",
            )

    def collect_evidence(self, state):
        try:
            components, time = state["component_ids"], state["incident"]["timestamp"]
            deployments = self.repository.recent_deployments(components, time)
            symptoms = self.repository.symptoms(components, time)
            memories = self.repository.historical_incidents(state["incident_id"])
            ids = graph_entity_ids(state["incident"], components, deployments, symptoms, memories)
            graph = self.repository.evidence_graph(ids, state["incident"]["timestamp"])
            evidence = build_evidence(
                state["incident"],
                state["dependency_paths"],
                components,
                deployments,
                symptoms,
                memories,
                graph,
            )
            evidence["retrieval_notices"] = notices(
                [{"truncated": state.get("traversal_truncated", False)}], deployments, symptoms
            )
            return stage(
                state,
                "collect_evidence",
                recent_deployments=evidence["recent_deployments"],
                observed_symptoms=evidence["observed_symptoms"],
                similar_incidents=evidence["similar_incidents"],
                evidence=evidence,
            )
        except Exception as exc:
            return stage(
                state,
                "collect_evidence",
                status="retrieval_failed",
                retrieval_error=f"Evidence retrieval failed ({type(exc).__name__}).",
            )

    def analyze_evidence(self, state):
        try:
            return stage(
                state, "analyze_evidence", raw_analysis=self.reasoner.analyze(state["evidence"])
            )
        except Exception as exc:
            return stage(
                state, "analyze_evidence", raw_analysis={}, validation_error=str(exc)[:1000]
            )

    def validate_hypotheses(self, state):
        if state.get("validation_error"):
            return stage(state, "validate_hypotheses", analysis_available=False)
        try:
            analysis = validate_analysis(state["raw_analysis"], state["evidence"])
            return stage(
                state,
                "validate_hypotheses",
                **analysis.model_dump(),
                validation_error=None,
                analysis_available=True,
            )
        except Exception as exc:
            return stage(
                state,
                "validate_hypotheses",
                validation_error=str(exc)[:1000],
                analysis_available=False,
            )

    def finalize(self, state):
        leading = state["hypotheses"][0] if state["hypotheses"] else {}
        return stage(
            state,
            "finalize",
            status="complete",
            raw_analysis={},
            highlight_entity_ids=[leading["cause_entity_id"]]
            if leading.get("cause_entity_id")
            else [],
            limitations=[
                *state["limitations"],
                *state["evidence"].get("retrieval_notices", []),
                "Hypotheses require verification; historical findings do not prove "
                "a current cause.",
            ],
        )

    def fallback(self, state):
        retrieval_error = state.get("retrieval_error")
        return stage(
            state,
            "fallback",
            analysis_available=False,
            raw_analysis={},
            hypotheses=[],
            highlight_entity_ids=[],
            status=state.get("status", "retrieval_failed")
            if retrieval_error
            else "analysis_unavailable",
            summary=retrieval_error
            or "Local model analysis unavailable. Retrieved evidence is preserved.",
            limitations=[
                retrieval_error or state.get("validation_error", "No validated analysis.")
            ],
        )
