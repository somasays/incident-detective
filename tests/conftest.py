"""Independent fixture repository for unit tests; live Cypher tests are explicitly opt-in."""

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from knowledge.evidence import build_evidence, graph_entity_ids


@pytest.fixture
def fixture_data():
    return json.loads((Path(__file__).parents[1] / "data/scenarios.json").read_text())


def dt(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class FixtureRepository:
    def list_namespaces(self):
        return ["incident-detective-v1"]

    """Test double, never used by the app. Derives results from fixture edges without Cypher."""

    def __init__(self, fixture):
        self.nodes = {n["id"]: copy.deepcopy(n) for n in fixture["nodes"]}
        self.edges = copy.deepcopy(fixture["edges"])

    def targets(self, id, rel):
        return [
            e["target"]
            for e in self.edges
            if e["source"] == id and e["type"] == rel and e["target"] in self.nodes
        ]

    def get_incident(self, id):
        if id not in self.nodes:
            return None
        root = self.targets(id, "AFFECTS")[0]
        return {
            **self.nodes[id],
            "affected_component": root,
            "affected_name": self.nodes[root]["name"],
        }

    def dependencies(self, id):
        root = self.targets(id, "AFFECTS")[0]
        paths = [[root]]
        for _ in range(3):
            new = [
                p + [target]
                for p in paths
                if len(p) == _ + 1
                for target in self.targets(p[-1], "DEPENDS_ON")
            ]
            paths.extend(new)
        return [{"path": p, "component_id": p[-1]} for p in sorted(paths)]

    def timed(self, label, rel, components, time):
        return [
            (n, c)
            for n in self.nodes.values()
            if n["label"] == label
            and dt(time) - timedelta(minutes=30) <= dt(n["timestamp"]) <= dt(time)
            for c in self.targets(n["id"], rel)
            if c in components
        ]

    def recent_deployments(self, components, time):
        return [
            {
                "deployment_id": n["id"],
                "deployed_at": n["timestamp"],
                "description": n["description"],
                "version": n["version"],
                "component_id": c,
            }
            for n, c in self.timed("Deployment", "CHANGED", components, time)
        ]

    def symptoms(self, components, time):
        return [
            {
                "symptom_id": n["id"],
                "observed_at": n["timestamp"],
                "symptom_type": n["type"],
                "message": n["message"],
                "component_id": c,
            }
            for n, c in self.timed("Symptom", "OBSERVED_ON", components, time)
        ]

    def historical_incidents(self, id):
        current_types = {self.nodes[s]["type"] for s in self.targets(id, "HAS_SYMPTOM")}
        memories = []
        for past in self.nodes.values():
            if past["label"] != "Incident" or dt(past["timestamp"]) >= dt(
                self.nodes[id]["timestamp"]
            ):
                continue
            shared = current_types & {
                self.nodes[s]["type"] for s in self.targets(past["id"], "HAS_SYMPTOM")
            }
            if not shared:
                continue
            findings = [
                {**f, "causes": [self.nodes[c] for c in self.targets(f["id"], "ATTRIBUTED_TO")]}
                for f in self.nodes.values()
                if f["label"] == "Finding"
                and f["confirmed"]
                and past["id"] in self.targets(f["id"], "EXPLAINS")
                and dt(f["created_at"]) <= dt(self.nodes[id]["timestamp"])
            ]
            memories.append(
                {
                    "id": past["id"],
                    "timestamp": past["timestamp"],
                    "summary": past["summary"],
                    "shared_symptoms": sorted(shared),
                    "confirmed_findings": findings,
                }
            )
        memories.sort(key=lambda m: m["id"])
        memories.sort(key=lambda m: m["timestamp"], reverse=True)
        memories.sort(key=lambda m: len(m["shared_symptoms"]), reverse=True)
        return memories[:5]

    def evidence_graph(self, ids, incident_time=None):
        return {
            "nodes": [self.nodes[id] for id in sorted(ids)],
            "edges": [e for e in self.edges if e["source"] in ids and e["target"] in ids],
        }


@pytest.fixture
def repository(fixture_data):
    return FixtureRepository(fixture_data)


def retrieve_evidence(repository, id="INC-104"):
    incident = repository.get_incident(id)
    paths = [r["path"] for r in repository.dependencies(id)]
    components = sorted({c for p in paths for c in p})
    deployments = repository.recent_deployments(components, incident["timestamp"])
    symptoms = repository.symptoms(components, incident["timestamp"])
    memories = repository.historical_incidents(id)
    ids = graph_entity_ids(incident, components, deployments, symptoms, memories)
    return build_evidence(
        incident, paths, components, deployments, symptoms, memories, repository.evidence_graph(ids)
    )


@pytest.fixture
def evidence(repository):
    return retrieve_evidence(repository)


@pytest.fixture
def valid_analysis():
    return {
        "summary": "A connector regression is plausible based on graph-retrieved evidence.",
        "hypotheses": [
            {
                "rank": 1,
                "title": "Possible connector deployment regression",
                "explanation": (
                    "deploy-014 changed event-connector before "
                    "the schema mismatch upstream of the API."
                ),
                "cause_entity_id": "deploy-014",
                "supporting_evidence_ids": [
                    "DEPLOY:deploy-014",
                    "SYMPTOM:schema-error-104",
                    "FINDING:finding-092",
                ],
                "contradicting_or_missing_evidence": ["The changed mapping has not been compared."],
                "next_check": "Compare connector schema mapping before and after the deployment.",
            }
        ],
        "limitations": ["Chronology and past findings do not establish current causality."],
    }
