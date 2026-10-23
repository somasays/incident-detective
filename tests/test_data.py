from datetime import UTC, datetime


def test_fixture_integrity(fixture_data):
    nodes = fixture_data["nodes"]
    by_id = {n["id"]: n for n in nodes}
    assert len(by_id) == len(nodes)
    assert 30 <= len(nodes) <= 45
    for n in nodes:
        for key in {"timestamp", "created_at"} & n.keys():
            assert n[key].endswith("Z")
            assert datetime.fromisoformat(n[key].replace("Z", "+00:00")).tzinfo == UTC
    for e in fixture_data["edges"]:
        assert e["source"] in by_id and e["target"] in by_id
    edges = fixture_data["edges"]
    signatures = {(e["source"], e["type"], e["target"]) for e in edges}
    assert len(signatures) == len(edges)
    allowed = {
        "DEPENDS_ON": ({"Component"}, {"Component"}),
        "CHANGED": ({"Deployment"}, {"Component"}),
        "AFFECTS": ({"Incident"}, {"Component"}),
        "HAS_SYMPTOM": ({"Incident"}, {"Symptom"}),
        "OBSERVED_ON": ({"Symptom"}, {"Component"}),
        "EXPLAINS": ({"Finding"}, {"Incident"}),
        "ATTRIBUTED_TO": ({"Finding"}, {"Deployment", "Component"}),
    }
    for e in edges:
        source, target = allowed[e["type"]]
        assert by_id[e["source"]]["label"] in source
        assert by_id[e["target"]]["label"] in target
    for f in (n for n in nodes if n["label"] == "Finding"):
        assert f["confirmed"] is True
        assert any(e["source"] == f["id"] and e["type"] == "EXPLAINS" for e in edges)
        assert any(e["source"] == f["id"] and e["type"] == "ATTRIBUTED_TO" for e in edges)
    assert by_id["INC-071"]["timestamp"] < by_id["INC-105"]["timestamp"]
    assert by_id["INC-092"]["timestamp"] < by_id["INC-104"]["timestamp"]


def test_scenario_paths_and_time_filtering(repository):
    assert ["analytics-api", "analytics-store", "ingestion-pipeline", "event-connector"] in [
        r["path"] for r in repository.dependencies("INC-104")
    ]
    assert [r["path"] for r in repository.dependencies("INC-105")] == [
        ["orders-api"],
        ["orders-api", "orders-database"],
    ]
    from conftest import retrieve_evidence

    a, b = retrieve_evidence(repository), retrieve_evidence(repository, "INC-105")
    assert [d["id"] for d in a["recent_deployments"]] == ["deploy-014"]
    assert b["recent_deployments"] == []
    assert {s["type"] for s in a["observed_symptoms"]} >= {"SCHEMA_MISMATCH", "HTTP_500"}
    assert {s["type"] for s in b["observed_symptoms"]} >= {
        "CONNECTION_POOL_EXHAUSTED",
        "REQUEST_TIMEOUT",
    }
    assert a["similar_incidents"][0]["id"] == "INC-092"
    assert b["similar_incidents"][0]["id"] == "INC-071"


def test_evidence_ids_and_no_noise(evidence):
    assert evidence["index"]["DEPLOY:deploy-014"]["minutes_before"] == 4
    assert evidence["index"]["SYMPTOM:schema-error-104"]["minutes_before"] == 1
    assert "FINDING:finding-092" in evidence["index"]
    graph_ids = {n["id"] for n in evidence["graph"]["nodes"]}
    assert not graph_ids & {"notification-worker", "deploy-015", "deploy-016", "future-schema"}
