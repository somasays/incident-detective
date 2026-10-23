"""Normalize graph results into stable, serializable, time-bounded evidence."""

from datetime import datetime


def minutes_before(timestamp: str, incident_time: str) -> float:
    return round(
        (
            datetime.fromisoformat(incident_time.replace("Z", "+00:00"))
            - datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        ).total_seconds()
        / 60,
        2,
    )


def build_evidence(incident, paths, component_ids, deployments, symptoms, memories, graph):
    deployments = [
        {
            "evidence_id": f"DEPLOY:{d['deployment_id']}",
            "id": d["deployment_id"],
            "timestamp": d["deployed_at"],
            "description": d["description"],
            "version": d["version"],
            "component": d["component_id"],
            "minutes_before": minutes_before(d["deployed_at"], incident["timestamp"]),
        }
        for d in deployments
    ]
    symptoms = [
        {
            "evidence_id": f"SYMPTOM:{s['symptom_id']}",
            "id": s["symptom_id"],
            "timestamp": s["observed_at"],
            "type": s["symptom_type"],
            "message": s["message"],
            "component": s["component_id"],
            "minutes_before": minutes_before(s["observed_at"], incident["timestamp"]),
        }
        for s in symptoms
    ]
    memories = [
        {
            **m,
            "evidence_id": f"INCIDENT:{m['id']}",
            "confirmed_findings": [
                {**f, "evidence_id": f"FINDING:{f['id']}"} for f in m["confirmed_findings"]
            ],
        }
        for m in memories
    ]
    evidence = {
        "incident": {**incident, "evidence_id": f"INCIDENT:{incident['id']}"},
        "dependency_paths": paths,
        "path_evidence": [{"evidence_id": "PATH:" + ">".join(p), "path": p} for p in paths],
        "component_ids": sorted(set(component_ids)),
        "recent_deployments": deployments,
        "observed_symptoms": symptoms,
        "similar_incidents": memories,
        "window_minutes": 30,
        "max_dependency_depth": 3,
        "graph": graph,
        "eligible_cause_ids": sorted(set(component_ids) | {d["id"] for d in deployments}),
    }
    evidence["index"] = evidence_index(evidence)
    return evidence


def evidence_index(evidence):
    items = [
        evidence["incident"],
        *evidence["path_evidence"],
        *evidence["recent_deployments"],
        *evidence["observed_symptoms"],
        *evidence["similar_incidents"],
    ]
    items.extend(f for m in evidence["similar_incidents"] for f in m["confirmed_findings"])
    return {item["evidence_id"]: item for item in items}


def graph_entity_ids(incident, component_ids, deployments, symptoms, memories):
    ids = {incident["id"], *component_ids}
    ids.update(d["deployment_id"] for d in deployments)
    ids.update(s["symptom_id"] for s in symptoms)
    for memory in memories:
        ids.add(memory["id"])
        for finding in memory["confirmed_findings"]:
            ids.add(finding["id"])
            ids.update(c["id"] for c in finding["causes"])
    return sorted(ids)


def model_evidence(evidence):
    # Complete relationship records are retained. Omit redundant index and UI graph properties.
    return {k: v for k, v in evidence.items() if k not in {"index", "graph"}} | {
        "retrieved_relationships": evidence["graph"]["edges"],
        "components": [n for n in evidence["graph"]["nodes"] if n["label"] == "Component"],
    }
