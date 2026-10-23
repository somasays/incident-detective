"""Real Cypher checks in an isolated namespace; enable with RUN_NEO4J_TESTS=1."""

import copy
import os
import uuid

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_NEO4J_TESTS") != "1", reason="Enable local Neo4j integration checks"
    ),
]


@pytest.fixture
def live_graph(fixture_data, monkeypatch):
    import seed as seed_module
    from config import Settings
    from knowledge import memory, queries
    from knowledge.db import Database
    from knowledge.queries import KnowledgeRepository
    from seed import seed

    namespace = "incident-detective-test-" + uuid.uuid4().hex[:12]
    prefix = namespace + "-"
    monkeypatch.setattr(queries, "DEMO_ID", namespace)
    monkeypatch.setattr(memory, "DEMO_ID", namespace)
    monkeypatch.setattr(seed_module, "DEMO_ID", namespace)
    fixture = copy.deepcopy(fixture_data)
    fixture["demo_id"] = namespace
    for n in fixture["nodes"]:
        n["id"] = prefix + n["id"]
    for e in fixture["edges"]:
        e["source"] = prefix + e["source"]
        e["target"] = prefix + e["target"]
    database = Database(Settings.from_env())
    database.wait_ready(attempts=3, delay=1)
    try:
        seed(database, fixture)
        yield database, KnowledgeRepository(database), prefix, namespace, fixture
    finally:
        database.write("MATCH (n {demo_id: $demo_id}) DETACH DELETE n", demo_id=namespace)
        database.close()


def test_real_dependency_queries(live_graph):
    _, repo, p, _, _ = live_graph
    assert [
        p + c for c in ["analytics-api", "analytics-store", "ingestion-pipeline", "event-connector"]
    ] in [r["path"] for r in repo.dependencies(p + "INC-104")]
    assert [p + "orders-api", p + "orders-database"] in [
        r["path"] for r in repo.dependencies(p + "INC-105")
    ]


def test_real_windows_symptoms_and_history(live_graph):
    _, repo, p, _, _ = live_graph
    from conftest import retrieve_evidence

    a, b = retrieve_evidence(repo, p + "INC-104"), retrieve_evidence(repo, p + "INC-105")
    assert [d["id"] for d in a["recent_deployments"]] == [p + "deploy-014"]
    assert not b["recent_deployments"]
    assert {s["type"] for s in a["observed_symptoms"]} >= {"HTTP_500", "SCHEMA_MISMATCH"}
    assert {s["type"] for s in b["observed_symptoms"]} >= {
        "CONNECTION_POOL_EXHAUSTED",
        "REQUEST_TIMEOUT",
    }
    assert a["similar_incidents"][0]["id"] == p + "INC-092"
    assert b["similar_incidents"][0]["id"] == p + "INC-071"
    assert a["similar_incidents"][0]["confirmed_findings"][0]["conclusion"].startswith(
        "Connector release"
    )
    assert b["similar_incidents"][0]["confirmed_findings"][0]["conclusion"].startswith(
        "Application connection pool"
    )
    assert not {n["id"] for n in a["graph"]["nodes"]} & {
        p + "deploy-015",
        p + "notification-worker",
    }


def test_real_seed_idempotent_and_confirmation(live_graph):
    db, repo, p, ns, fixture = live_graph
    from conftest import retrieve_evidence

    from knowledge.memory import confirm_finding
    from seed import seed

    seed(db, fixture)
    assert (
        db.read("MATCH (n {demo_id: $demo_id}) RETURN count(n) AS count", demo_id=ns)[0]["count"]
        == 37
    )
    count = db.read(
        "MATCH (a {demo_id: $demo_id})-[r]->(b {demo_id: $demo_id}) RETURN count(r) AS count",
        demo_id=ns,
    )
    assert count[0]["count"] == 49
    evidence = retrieve_evidence(repo, p + "INC-104")
    args = (db, p + "INC-104", p + "deploy-014", "Verified isolated test finding", evidence)
    id = confirm_finding(*args, user_confirmed=True)
    assert confirm_finding(*args, user_confirmed=True) == id
    rows = db.read(
        "MATCH (f:Finding {id: $id, demo_id: $demo_id})-[r]->(n) "
        "RETURN type(r) AS type, n.id AS id",
        id=id,
        demo_id=ns,
    )
    assert {(r["type"], r["id"]) for r in rows} == {
        ("EXPLAINS", p + "INC-104"),
        ("ATTRIBUTED_TO", p + "deploy-014"),
    }


def test_real_ablation_no_removed_deployment(live_graph):
    db, repo, p, ns, _ = live_graph
    from conftest import retrieve_evidence

    db.write(
        "MATCH (d:Deployment {id: $id, demo_id: $demo_id}) DETACH DELETE d",
        id=p + "deploy-014",
        demo_id=ns,
    )
    evidence = retrieve_evidence(repo, p + "INC-104")
    assert not evidence["recent_deployments"]
    assert p + "deploy-014" not in evidence["eligible_cause_ids"]
    assert p + "deploy-014" not in {n["id"] for n in evidence["graph"]["nodes"]}


def test_namespace_isolation(live_graph):
    db, repo, p, ns, _ = live_graph
    # Inject same symptom type and a fresh deployment into a different namespace.
    foreign = ns + "-foreign"
    try:
        db.write(
            "CREATE (s:Symptom {id: $id, demo_id: $scope, type:'SCHEMA_MISMATCH', "
            "timestamp:'2026-10-21T10:41:00Z'}) "
            "WITH s MATCH (c:Component {id: $component}) CREATE (s)-[:OBSERVED_ON]->(c)",
            id=foreign,
            scope=foreign,
            component=p + "ingestion-pipeline",
        )
        rows = repo.symptoms([p + "ingestion-pipeline"], "2026-10-21T10:42:00Z")
        assert foreign not in {r["symptom_id"] for r in rows}
    finally:
        db.write("MATCH (n {demo_id: $scope}) DETACH DELETE n", scope=foreign)


def test_graph_browser_paginates_and_preserves_real_edges(live_graph):
    from knowledge.ontology import LABELS, RELATIONSHIPS

    _, repo, _, namespace, _ = live_graph
    seen, cursor = [], ""
    while True:
        page = repo.graph_page(list(LABELS), list(RELATIONSHIPS), after_id=cursor, node_limit=7)
        assert len(page["nodes"]) <= 7
        ids = {n["id"] for n in page["nodes"]}
        assert all(n["demo_id"] == namespace for n in page["nodes"])
        assert all(e["source"] in ids and e["target"] in ids for e in page["edges"])
        seen.extend(n["id"] for n in page["nodes"])
        if not page["has_more_nodes"]:
            break
        cursor = page["nodes"][-1]["id"]
    assert len(seen) == len(set(seen)) == 37
    complete = repo.graph_page(list(LABELS), list(RELATIONSHIPS))
    assert len(complete["edges"]) == 49
    capped = repo.graph_page(list(LABELS), list(RELATIONSHIPS), edge_limit=3)
    assert len(capped["edges"]) == 3 and capped["has_more_edges"]
    filtered = repo.graph_page(["Component"], ["DEPENDS_ON"])
    assert len(filtered["nodes"]) == 11
    assert all(e["type"] == "DEPENDS_ON" for e in filtered["edges"])


@pytest.mark.llm
@pytest.mark.skipif(os.getenv("RUN_OLLAMA_TESTS") != "1", reason="Enable real local model check")
def test_real_model_ablation_remains_grounded(live_graph):
    from agent.graph import build_investigator
    from agent.reasoning import OllamaReasoner
    from ui.graph_view import build_network

    db, repo, p, ns, _ = live_graph
    removed = p + "deploy-014"
    db.write(
        "MATCH (d:Deployment {id: $id, demo_id: $demo_id}) DETACH DELETE d", id=removed, demo_id=ns
    )
    result = build_investigator(repo, OllamaReasoner()).invoke({"incident_id": p + "INC-104"})
    assert result["status"] == "complete", result.get("validation_error")
    assert result["analysis_available"]
    assert result["evidence"]["recent_deployments"] == []
    assert removed not in result["evidence"]["eligible_cause_ids"]
    assert "deploy-014" not in str(result["hypotheses"])
    assert removed not in result["highlight_entity_ids"]
    assert all("deploy-014" not in n["id"] for n in build_network(result["evidence"], result).nodes)
