"""Public entry point for temporal evidence retrieval and hypothesis investigation."""

import config  # noqa: F401 -- disable inherited tracing before importing LangGraph

# isort: split
from agent.evidence_workflow import build_evidence_workflow
from agent.investigation_loop import build_hypothesis_loop
from agent.temporal_reasoning import (
    OpenAITemporalReasoner,
    TemporalReasoner,
    model_context,
    validate_numerical_claims,
    validate_temporal_analysis,
)

__all__ = [
    "OpenAITemporalReasoner",
    "TemporalReasoner",
    "build_temporal_investigator",
    "model_context",
    "validate_numerical_claims",
    "validate_temporal_analysis",
]


def build_temporal_investigator(repository, reasoner=None, *, limits=None, tools=None):
    """Compile the evidence-only path or the bounded model-backed hypothesis loop."""
    if reasoner is None:
        return build_evidence_workflow(repository)
    return build_hypothesis_loop(repository, reasoner, limits=limits, tools=tools)
