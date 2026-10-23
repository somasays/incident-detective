from typing import Any, TypedDict


class InvestigationState(TypedDict, total=False):
    traversal_truncated: bool
    incident_id: str
    incident: dict[str, Any]
    dependency_paths: list[list[str]]
    component_ids: list[str]
    recent_deployments: list[dict]
    observed_symptoms: list[dict]
    similar_incidents: list[dict]
    evidence: dict[str, Any]
    raw_analysis: dict[str, Any]
    hypotheses: list[dict]
    summary: str
    limitations: list[str]
    validation_error: str | None
    retrieval_error: str | None
    analysis_available: bool
    status: str
    stages: list[str]
    highlight_entity_ids: list[str]
