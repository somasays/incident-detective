from copy import deepcopy

import pytest

from agent.graph import build_investigator


class Reasoner:
    def __init__(self, analysis):
        self.analysis = analysis
        self.calls = 0

    def analyze(self, evidence):
        self.calls += 1
        if isinstance(self.analysis, Exception):
            raise self.analysis
        return deepcopy(self.analysis)


def test_langgraph_execution(repository, valid_analysis):
    reasoner = Reasoner(valid_analysis)
    graph = build_investigator(repository, reasoner)
    result = graph.invoke({"incident_id": "INC-104"}, config={"recursion_limit": 12})
    assert result["stages"] == [
        "load_incident",
        "traverse_dependencies",
        "collect_evidence",
        "analyze_evidence",
        "validate_hypotheses",
        "finalize",
    ]
    assert result["analysis_available"]
    assert result["status"] == "complete"
    assert result["highlight_entity_ids"] == ["deploy-014"]
    assert reasoner.calls == 1
    edges = {(e.source, e.target) for e in graph.get_graph().edges}
    assert ("__start__", "load_incident") in edges
    assert ("validate_hypotheses", "fallback") in edges
    assert ("validate_hypotheses", "finalize") in edges
    assert ("finalize", "__end__") in edges


@pytest.mark.parametrize("output", [{"invalid": True}, ConnectionError("Ollama unavailable")])
def test_fallback_preserves_evidence(repository, output):
    result = build_investigator(repository, Reasoner(output)).invoke({"incident_id": "INC-104"})
    assert result["stages"][-1] == "fallback"
    assert result["status"] == "analysis_unavailable"
    assert not result["analysis_available"]
    assert result["hypotheses"] == []
    assert result["highlight_entity_ids"] == []
    assert result["evidence"]["graph"]["nodes"]
    assert result["evidence"]["recent_deployments"][0]["id"] == "deploy-014"


def test_missing_incident_safely_exits(repository):
    reasoner = Reasoner(None)
    result = build_investigator(repository, reasoner).invoke({"incident_id": "missing"})
    assert result["status"] == "not_found"
    assert result["stages"] == ["load_incident", "fallback"]
    assert reasoner.calls == 0


def test_graph_failure_safely_exits(repository, monkeypatch):
    def broken(*args):
        raise ConnectionError("database down")

    monkeypatch.setattr(repository, "dependencies", broken)
    reasoner = Reasoner(None)
    result = build_investigator(repository, reasoner).invoke({"incident_id": "INC-104"})
    assert result["status"] == "retrieval_failed"
    assert result["stages"] == ["load_incident", "traverse_dependencies", "fallback"]
    assert reasoner.calls == 0


def test_evidence_ablation(repository, valid_analysis):
    repository.nodes.pop("deploy-014")
    repository.edges = [e for e in repository.edges if e["source"] != "deploy-014"]
    analysis = deepcopy(valid_analysis)
    analysis["hypotheses"][0].update(
        title="Possible schema incompatibility",
        cause_entity_id="ingestion-pipeline",
        explanation="A schema mismatch was observed on ingestion-pipeline.",
        supporting_evidence_ids=["SYMPTOM:schema-error-104"],
    )
    result = build_investigator(repository, Reasoner(analysis)).invoke({"incident_id": "INC-104"})
    assert result["status"] == "complete"
    assert result["evidence"]["recent_deployments"] == []
    assert "DEPLOY:deploy-014" not in result["evidence"]["index"]
    assert "deploy-014" not in result["highlight_entity_ids"]
    assert "deploy-014" not in str(result["hypotheses"])
    # A model trying to retain the removed deployment is rejected, never silently repaired.
    result = build_investigator(repository, Reasoner(valid_analysis)).invoke(
        {"incident_id": "INC-104"}
    )
    assert result["stages"][-1] == "fallback"


def test_weak_evidence_does_not_force_a_hypothesis(repository):
    analysis = {
        "summary": "Evidence is insufficient to rank a cause.",
        "hypotheses": [],
        "limitations": ["Additional observations are needed."],
    }
    result = build_investigator(repository, Reasoner(analysis)).invoke({"incident_id": "INC-104"})
    assert result["status"] == "complete"
    assert result["analysis_available"]
    assert result["hypotheses"] == []
    assert result["highlight_entity_ids"] == []
    assert result["evidence"]["graph"]["nodes"]
