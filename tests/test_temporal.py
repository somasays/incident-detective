"""Temporal resolution/grounding and real database proofs for the approved v2 graph."""

import json
import os
from copy import deepcopy

import pytest

from agent.temporal import build_temporal_investigator, model_context, validate_temporal_analysis
from knowledge.db import Database
from knowledge.diagnostic_tools import empty_package
from knowledge.temporal_fixture import DATASET, PREFIX, build_fixture
from knowledge.temporal_queries import TemporalRepository, resolve_request
from knowledge.temporal_seed import seed_temporal, validate_fixture
from ui.temporal_report import report_html


@pytest.fixture
def temporal_catalog():
    return [n for n in build_fixture()["nodes"] if n["label"] in {"Component", "System"}]


def test_fixture_is_valid_and_contains_all_approved_types():
    fixture = validate_fixture(build_fixture())
    assert len({n["label"] for n in fixture["nodes"]}) == 14
    assert not any(n["label"] in {"K8sPod", "K8sNode"} for n in fixture["nodes"])
    assert fixture == build_fixture()  # repeatable source records and IDs


def test_question_time_and_alias_resolution(temporal_catalog):
    request = resolve_request("What was wrong with payment API at 3AM today?", temporal_catalog)
    assert request["rootId"] == PREFIX + "payments-api"
    assert request["effectiveAt"] == "2026-10-23T01:00:00Z"
    assert request["knowledgeAsOf"] == "2026-10-23T08:05:00Z"
    replay = resolve_request("payment API at 3AM today", temporal_catalog, mode="known_then")
    assert replay["knowledgeAsOf"] == replay["effectiveAt"]


@pytest.mark.parametrize(
    "question", ["Why is nonexistent service slow?", "payments API and auth service are slow"]
)
def test_unknown_and_ambiguous_service_requires_clarification(temporal_catalog, question):
    with pytest.raises(ValueError):
        resolve_request(question, temporal_catalog)


def test_unsupported_time_does_not_silently_become_now(temporal_catalog):
    with pytest.raises(ValueError, match="time expression"):
        resolve_request("payments API at 03:00 yesterday", temporal_catalog)
    with pytest.raises(ValueError, match="coverage"):
        resolve_request("payments API", temporal_catalog, at="2026-10-24T03:00:00Z")


def test_numeric_and_reference_grounding():
    evidence = {"id": "e1", "entityId": "volume", "provisionedIops": 300}
    package = {
        "index": {"e1": evidence},
        "graph": {"nodes": [{"id": "volume", "label": "StorageVolume"}]},
        "measurements": [],
    }
    raw = {
        "summary": "A storage change is plausible.",
        "limitations": ["Verification needed"],
        "hypotheses": [
            {
                "rank": 1,
                "title": "Possible storage bottleneck",
                "explanation": "The allocation was 300 IOPS.",
                "cause_entity_id": "volume",
                "supporting_evidence_ids": ["e1"],
                "contradicting_or_missing_evidence": ["No device inspection."],
                "next_check": "Inspect allocation and queue depth.",
            }
        ],
    }
    assert validate_temporal_analysis(raw, package)
    for changes in [
        {"supporting_evidence_ids": ["fabricated"]},
        {"cause_entity_id": "missing"},
        {"rank": 2},
        {"explanation": "The allocation was 9000 IOPS."},
    ]:
        altered = deepcopy(raw)
        altered["hypotheses"][0].update(changes)
        with pytest.raises(ValueError):
            validate_temporal_analysis(altered, package)


def test_model_sees_unfamiliar_properties_and_original_observation_records():
    package = empty_package({})
    package["states"] = [{"id": "s1", "ioScheduler": "deadline", "customQuota": 42}]
    package["graph"]["edges"] = [
        {
            "id": "release-code",
            "source": "r1",
            "target": "code1",
            "type": "INCLUDES",
        }
    ]
    package["observations"] = [
        {
            "id": "o1",
            "kind": "error",
            "errorType": "NEW_VENDOR_EVENT",
            "message": "unfamiliar source event",
            "sourceRef": "local.json#/4",
            "vendorDiagnostic": "quota contention",
        }
    ]
    context = model_context(package)
    assert context["states"] == package["states"]
    assert context["observations"] == package["observations"]
    assert context["evidence_relationships"] == package["graph"]["edges"]


LIVE = pytest.mark.skipif(os.getenv("RUN_NEO4J_TESTS") != "1", reason="Requires local Neo4j")


@pytest.fixture(scope="module")
def temporal_db():
    with Database() as db:
        seed_temporal(db)
        yield db


def retrieve(db, question="payments API at 3AM today", **options):
    repository = TemporalRepository(db)
    return build_temporal_investigator(repository).invoke(
        {"question": question, "options": options}, config={"recursion_limit": 12}
    )["package"]


@LIVE
@pytest.mark.integration
def test_real_historical_and_current_states_and_topology(temporal_db):
    past = retrieve(temporal_db)
    assert past["status"] == "evidence_only", past.get("error")
    allocation = [s for s in past["states"] if "provisionedIops" in s]
    assert [s["provisionedIops"] for s in allocation] == [3000, 300, 3000]
    assert any(
        e["source"] == PREFIX + "auth-service-workload" and e["target"] == PREFIX + "cluster-east"
        for e in past["topology"]["edges"]
    )
    present = retrieve(temporal_db, "Why is payments API slow now?")
    assert [s["provisionedIops"] for s in present["states"] if "provisionedIops" in s] == [3000]
    assert any(
        e["source"] == PREFIX + "auth-service-workload" and e["target"] == PREFIX + "cluster-west"
        for e in present["topology"]["edges"]
    )
    assert [step["stage"] for step in past["stages"]] == [
        "resolve_question", "reconstruct_topology", "collect_temporal_evidence", "finalize"
    ]
    assert "<iframe" in report_html(past)


@LIVE
@pytest.mark.integration
def test_real_metric_values_errors_code_and_noise_filtering(temporal_db):
    package = retrieve(temporal_db)
    latency = next(m for m in package["measurements"] if m["entityId"] == PREFIX + "payments-api")
    assert (latency["baseline"], latency["incident"], latency["recovery"]) == (85, 1650, 92)
    assert latency["ratio"] == round(1650 / 85, 4)
    assert any(
        o.get("message") == "query waiting on DataFileRead; elapsed_ms=1278"
        and o["eventCount"] == 420
        for o in package["observations"]
    )
    assert PREFIX + "payments-unreleased" not in package["index"]
    assert PREFIX + "notification-noise" not in package["index"]
    assert PREFIX + "payments-r18-code" in package["index"]
    assert PREFIX + "auth-r8" in package["index"]  # older than recent-change window
    assert package["historicalFindings"]


@LIVE
@pytest.mark.integration
def test_real_known_then_excludes_late_findings_recovery_and_corrections(temporal_db):
    package = retrieve(temporal_db, mode="known_then")
    assert package["status"] == "evidence_only", package.get("error")
    assert all(m["finding"]["id"] != PREFIX + "finding-201" for m in package["historicalFindings"])
    assert PREFIX + "late-storage-alert" not in package["index"]
    assert PREFIX + "storage-18" not in package["index"]
    assert PREFIX + "volume-low" in package["index"]
    assert PREFIX + "volume-low-revision2" not in package["index"]
    assert all("recovery" not in m for m in package["measurements"])


@LIVE
@pytest.mark.integration
def test_real_graph_ablation_changes_scope_with_all_events_unchanged(temporal_db):
    with temporal_db.driver.session(database=temporal_db.settings.neo4j_database) as session:
        tx = session.begin_transaction()
        try:
            tx.run(
                "CYPHER 25 MATCH (:Component {id:$root})-[r:DEPENDS_ON]->"
                "(:Component {id:$target}) DELETE r",
                root=PREFIX + "payments-api",
                target=PREFIX + "auth-service",
            ).consume()

            class TransactionDatabase:
                def read(self, query, **params):
                    return tx.run(query, **params).data()

            package = retrieve(TransactionDatabase())
            assert package["status"] == "evidence_only", package.get("error")
            assert PREFIX + "auth-volume" not in package["index"]
            assert PREFIX + "storage-17" not in package["index"]
            assert PREFIX + "auth-db-wait" not in package["index"]
        finally:
            tx.rollback()  # the user's prepared dataset is preserved


@LIVE
@pytest.mark.integration
def test_real_seed_is_idempotent_and_fixtures_remain_separate(temporal_db):
    before = temporal_db.read(
        "CYPHER 25 MATCH (n:Component {demo_id:$legacy}) RETURN count(n) AS count",
        legacy="incident-detective-v1",
    )
    counts = seed_temporal(temporal_db)
    assert counts["nodes"] == len(build_fixture()["nodes"])
    assert (
        temporal_db.read(
            "CYPHER 25 MATCH (n:Component {datasetId:$dataset}) RETURN count(n) AS count",
            dataset=DATASET,
        )[0]["count"]
        == 10
    )
    assert before == temporal_db.read(
        "CYPHER 25 MATCH (n:Component {demo_id:$legacy}) RETURN count(n) AS count",
        legacy="incident-detective-v1",
    )


@LIVE
@pytest.mark.integration
def test_real_other_questions_use_their_own_evidence(temporal_db):
    billing = retrieve(temporal_db, "Why does billing API throw errors?")
    profile = retrieve(temporal_db, "Why is profile service unstable?")
    assert PREFIX + "ledger-r4-code" in billing["index"]
    assert any(o.get("errorType") == "SCHEMA_MISMATCH" for o in billing["observations"])
    assert PREFIX + "cache-config-9" in profile["index"]
    assert any(o.get("errorType") == "MAX_CLIENTS_REACHED" for o in profile["observations"])
    assert PREFIX + "storage-17" not in billing["index"]
    assert PREFIX + "storage-17" not in profile["index"]


def test_export_escapes_source_text():
    package = {
        "request": {"question": '<img src="https://example.com/x">'},
        "observations": [{"message": "<script>bad()</script>"}],
    }
    document = report_html(package)
    assert "&lt;script&gt;bad()&lt;/script&gt;" in document
    assert '<img src="https://example.com/x">' not in document
    json.dumps(package)
