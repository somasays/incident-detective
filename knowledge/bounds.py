"""Explicit per-investigation budgets; graph size must not become prompt size."""

MAX_COMPONENTS = 64
MAX_NEIGHBORS = 16
MAX_DEPTH = 3
MAX_DEPLOYMENTS = 50
MAX_SYMPTOMS = 100
MAX_MEMORY_TYPES = 8
MAX_MEMORY_CANDIDATES = 100


def notices(paths, deployments, symptoms):
    result = [
        "Dependency search keeps one discovered path per component, to depth 3, "
        "with at most 64 components and 16 dependencies per component."
    ]
    if any(p.get("truncated") for p in paths):
        result.append("Dependency retrieval was truncated; absence of evidence is inconclusive.")
    if len(deployments) >= MAX_DEPLOYMENTS:
        result.append("Deployment retrieval reached its 50-record cap; more changes may exist.")
    if len(symptoms) >= MAX_SYMPTOMS:
        result.append("Symptom retrieval reached its 100-record cap; more symptoms may exist.")
    result.append(
        "Historical matching examines at most 8 symptom types and 100 candidates per type."
    )
    return result
