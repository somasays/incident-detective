"""Real Neo4j construction, checkpoint atomicity, provenance and topology history."""

import json
import os
import uuid

import pytest

from ingestion.models import Source
from ingestion.runner import poll_once, poll_source
from ingestion.store import GraphWriter
from knowledge.db import Database
from knowledge.ontology import ensure_schema
from knowledge.queries import KnowledgeRepository
from scripts.create_ingestion_example import append, catalog, trace_export

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_NEO4J_TESTS") != "1",
        reason="Enable live Neo4j checks",
    ),
]


@pytest.fixture
def live_inputs(tmp_path):
    namespace = "inputs-test-" + uuid.uuid4().hex[:12]
    database = Database()
    ensure_schema(database)
    writer = GraphWriter(database, namespace)

    def source(adapter, id=None, environment="local"):
        path = tmp_path / f"{id or adapter}.jsonl"
        path.touch(exist_ok=True)
        return Source(id=id or adapter, adapter=adapter, environment=environment, path=path)

    try:
        yield database, writer, source, KnowledgeRepository(database, namespace)
    finally:
        database.write("MATCH (n {demo_id:$ns}) DETACH DELETE n", ns=namespace)
        database.close()


def incident(id="a1", timestamp="2026-10-23T10:42:00Z"):
    return {
        "id": id,
        "service": "web-api",
        "timestamp": timestamp,
        "summary": "Report failure",
        "severity": "SEV-1",
        "status": "open",
    }


def test_construct_incrementally_and_preserve_as_of_topology(live_inputs):
    db, writer, source, repo = live_inputs
    manifest, trace, alerts = source("catalog"), source("otlp"), source("incidents")
    append(manifest.path, catalog("2026-10-23T10:00:00Z"))
    append(trace.path, trace_export())
    append(alerts.path, incident())
    reports = poll_once(writer, [manifest, trace, alerts])
    assert not any("error" in r for r in reports), reports
    before = repo.dependencies(repo.list_incidents()[0]["id"])
    assert any(r["component_id"].endswith(":source-adapter") for r in before)
    assert len(before) == 4
    count = db.read("MATCH (n {demo_id:$ns}) RETURN count(n) AS n", ns=writer.namespace)[0]["n"]
    assert all(r["records"] == 0 for r in poll_once(writer, [manifest, trace, alerts]))
    assert (
        db.read("MATCH (n {demo_id:$ns}) RETURN count(n) AS n", ns=writer.namespace)[0]["n"]
        == count
    )
    append(manifest.path, catalog("2026-10-23T11:00:00Z", switched=True))
    append(alerts.path, incident("a2", "2026-10-23T11:02:00Z"))
    assert not any("error" in r for r in poll_once(writer, [manifest, alerts]))
    incidents = repo.list_incidents()
    old = next(i for i in incidents if i["timestamp"].startswith("2026-10-23T10"))
    new = next(i for i in incidents if i["timestamp"].startswith("2026-10-23T11"))
    assert any(r["component_id"].endswith(":source-adapter") for r in repo.dependencies(old["id"]))
    after = repo.dependencies(new["id"])
    assert any(r["component_id"].endswith(":backup-adapter") for r in after)
    assert not any(r["component_id"].endswith(":source-adapter") for r in after)
    old_view = repo.graph_page(["Component"], ["DEPENDS_ON"], incident_time=old["timestamp"])
    new_view = repo.graph_page(["Component"], ["DEPENDS_ON"], incident_time=new["timestamp"])
    assert any(
        e["source"].endswith(":loader") and e["target"].endswith(":source-adapter")
        for e in old_view["edges"]
    )
    assert not any(e["target"].endswith(":source-adapter") for e in new_view["edges"])
    assert any(e["target"].endswith(":backup-adapter") for e in new_view["edges"])
    graph = repo.evidence_graph([r["component_id"] for r in before], old["timestamp"])
    observed = [e for e in graph["edges"] if e["properties"]["method"] == "observed_trace"]
    assert len(observed) == 1 and observed[0]["properties"]["source_ref"].endswith(":1")
    components = [n for n in graph["nodes"] if n["label"] == "Component"]
    assert next(n for n in components if n["name"] == "loader")["type"] == "pipeline"


def test_graph_writes_and_cursor_roll_back_together(live_inputs):
    db, writer, source, _ = live_inputs
    logs = source("logs")
    base = {
        "id": "log1",
        "service": "api",
        "timestamp": "2026-10-23T10:42:00Z",
        "severity": "ERROR",
        "error_type": "HTTP_500",
        "message": "failure",
    }
    append(logs.path, base)
    append(
        logs.path, base | {"id": "log2", "incident_id": "not-imported", "incident_source": "alerts"}
    )
    with pytest.raises(ValueError, match="Unresolved"):
        poll_source(writer, logs)
    assert writer.state(logs)["offset"] == 0
    assert not db.read("MATCH (n:Symptom {demo_id:$ns}) RETURN n", ns=writer.namespace)


def test_duplicate_event_replay_and_conflict_detection(live_inputs):
    db, writer, source, _ = live_inputs
    releases = source("deployments")
    event = {
        "id": "r1",
        "service": "api",
        "timestamp": "2026-10-23T10:38:00Z",
        "version": "1.0",
        "description": "release",
    }
    append(releases.path, event)
    poll_source(writer, releases)
    append(releases.path, event)
    poll_source(writer, releases)
    assert (
        db.read("MATCH (d:Deployment {demo_id:$ns}) RETURN count(d) AS n", ns=writer.namespace)[0][
            "n"
        ]
        == 1
    )
    offset = writer.state(releases)["offset"]
    append(releases.path, event | {"version": "evil-conflict"})
    with pytest.raises(ValueError, match="Conflicting payload"):
        poll_source(writer, releases)
    assert writer.state(releases)["offset"] == offset


def test_stale_worker_revision_cannot_advance_cursor(live_inputs):
    _, writer, source, _ = live_inputs
    releases = source("deployments")
    stale = writer.state(releases)
    append(
        releases.path,
        {
            "id": "r1",
            "service": "api",
            "timestamp": "2026-10-23T10:38:00Z",
            "version": "1.0",
            "description": "release",
        },
    )
    poll_source(writer, releases)
    with pytest.raises(ValueError, match="cursor changed"):
        writer.commit(releases, stale, [], {"offset": 0})
    assert writer.state(releases)["offset"] > 0


def test_out_of_order_manifest_is_rejected_without_rewriting_history(live_inputs):
    _, writer, source, _ = live_inputs
    manifest = source("catalog")
    append(manifest.path, catalog("2026-10-23T11:00:00Z"))
    poll_source(writer, manifest)
    offset = writer.state(manifest)["offset"]
    append(manifest.path, catalog("2026-10-23T10:00:00Z", switched=True))
    with pytest.raises(ValueError, match="chronological"):
        poll_source(writer, manifest)
    assert writer.state(manifest)["offset"] == offset


def test_time_index_is_used_and_results_are_bounded(live_inputs):
    db, writer, source, repo = live_inputs
    alerts = source("incidents")
    append(alerts.path, incident())
    poll_source(writer, alerts)
    component = repo.list_incidents()[0]["affected_component"]
    db.write(
        "MATCH (c:Component {id:$component}) UNWIND range(1,250) AS i "
        "CREATE (s:Symptom {id:$ns+':noise:'+toString(i),demo_id:$ns,component_id:$component, "
        "timestamp:'2026-10-23T10:41:00Z',timestamp_ms:1792752060000, "
        "type:'HTTP_500', message:'synthetic burst'})-[:OBSERVED_ON]->(c)",
        component=component,
        ns=writer.namespace,
    )
    assert len(repo.symptoms([component], "2026-10-23T10:42:00Z")) == 100
    from knowledge.queries import RECENT_SYMPTOMS

    with db.driver.session(database=db.settings.neo4j_database) as session:
        summary = session.run(
            "PROFILE " + RECENT_SYMPTOMS,
            demo_id=writer.namespace,
            component_ids=[component],
            at=1792752120000,
            since=1792750320000,
            limit=100,
        ).consume()
    assert "Index" in json.dumps(summary.profile)


def test_confirmation_uses_constructed_graph_scope(live_inputs):
    from conftest import retrieve_evidence

    from knowledge.memory import confirm_finding

    db, writer, source, repo = live_inputs
    manifest, alerts = source("catalog"), source("incidents")
    append(manifest.path, catalog("2026-10-23T10:00:00Z"))
    append(alerts.path, incident())
    poll_source(writer, manifest)
    poll_source(writer, alerts)
    current = repo.list_incidents()[0]
    evidence = retrieve_evidence(repo, current["id"])
    args = (db, current["id"], current["affected_component"], "Verified isolated test", evidence)
    finding = confirm_finding(*args, user_confirmed=True)
    assert confirm_finding(*args, user_confirmed=True) == finding
    assert (
        db.read("MATCH (f:Finding {id:$id}) RETURN f.demo_id AS ns", id=finding)[0]["ns"]
        == writer.namespace
    )
