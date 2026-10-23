"""Construction rules, source identity, and incremental input semantics."""

import copy
import json

import pytest

from ingestion.adapters import Adapter
from ingestion.models import Edge, Node, Source, Sources
from ingestion.runner import fingerprint, poll_source
from knowledge.ontology import epoch_ms, validate_edge
from scripts.create_ingestion_example import catalog, trace_export


def source(tmp_path, adapter="catalog", id="catalog", environment="local"):
    path = tmp_path / f"{id}.jsonl"
    path.touch(exist_ok=True)
    return Source(id=id, adapter=adapter, environment=environment, path=path)


def test_catalog_constructs_only_declared_edges_with_provenance(tmp_path):
    adapter = Adapter("inputs-test", source(tmp_path))
    mutation = adapter.convert(catalog("2026-10-23T10:00:00Z"), 1)
    assert len(mutation.nodes) == 4
    assert len(mutation.edges) == 2
    assert all(
        e.kind == "DEPENDS_ON" and e.properties["method"] == "declared" for e in mutation.edges
    )
    assert all(n.properties["source_ref"].endswith(":1") for n in mutation.nodes)
    assert not any(e.source.endswith(":loader") for e in mutation.edges)


@pytest.mark.parametrize("mode", ["unknown", "self", "duplicate"])
def test_invalid_catalog_does_not_invent_targets(tmp_path, mode):
    record = catalog("2026-10-23T10:00:00Z")
    if mode == "duplicate":
        record["services"].append(record["services"][0])
    else:
        record["services"][0]["depends_on"] = ["unknown" if mode == "unknown" else "web-api"]
    with pytest.raises(ValueError):
        Adapter("inputs-test", source(tmp_path)).convert(record, 1)


def test_trace_builds_dependency_from_cross_service_parent_child(tmp_path):
    mutation = Adapter("inputs-test", source(tmp_path, "otlp")).convert(trace_export(), 2)
    assert len(mutation.edges) == 1
    edge = mutation.edges[0]
    assert edge.source.endswith(":loader") and edge.target.endswith(":source-adapter")
    assert edge.properties["method"] == "observed_trace"
    assert edge.properties["valid_to_ms"] - edge.properties["valid_from_ms"] == 15 * 60_000
    assert edge.properties["parent_span_id"] == "1" * 16


@pytest.mark.parametrize("mode", ["missing_parent", "same_service", "wrong_kind"])
def test_trace_cooccurrence_is_not_a_dependency(tmp_path, mode):
    record = trace_export()
    if mode == "missing_parent":
        record["resourceSpans"].pop(0)
    elif mode == "same_service":
        record["resourceSpans"][1]["resource"]["attributes"][0]["value"]["stringValue"] = "loader"
    else:
        record["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["kind"] = 1
    mutation = Adapter("inputs-test", source(tmp_path, "otlp")).convert(record, 1)
    assert not mutation.edges
    if mode == "missing_parent":
        assert mutation.warnings


def test_environments_have_distinct_component_identities(tmp_path):
    a = Adapter("inputs-test", source(tmp_path, environment="local"))
    b = Adapter("inputs-test", source(tmp_path, environment="staging"))
    assert a.component_id("api") != b.component_id("api")


def test_ontology_rejects_bad_properties_and_relationships():
    with pytest.raises(ValueError, match="Unknown"):
        Node("Person", "x", {})
    with pytest.raises(ValueError, match="Unknown"):
        Node(
            "Component",
            "x",
            {"name": "x", "type": "service", "description": "x", "magic_cause": True},
        )
    with pytest.raises(ValueError, match="Forbidden"):
        Edge("CHANGED", "x", "y", "Symptom", "Component", {})
    validate_edge("CHANGED", "Deployment", "Component")
    with pytest.raises(ValueError, match="UTC"):
        epoch_ms("2026-10-23T10:00:00")


def test_info_logs_do_not_expand_graph_and_error_logs_do_not_create_causality(tmp_path):
    adapter = Adapter("inputs-test", source(tmp_path, "logs"))
    record = {
        "id": "e1",
        "service": "api",
        "timestamp": "2026-10-23T10:00:00Z",
        "severity": "INFO",
        "message": "all good",
    }
    assert not adapter.convert(record, 1).nodes
    record.update(severity="ERROR", error_type="HTTP_500")
    result = adapter.convert(record, 2)
    assert [n.label for n in result.nodes] == ["Component", "Symptom"]
    assert [e.kind for e in result.edges] == ["OBSERVED_ON"]


class FakeWriter:
    namespace = "inputs-test"

    def __init__(self):
        self.checkpoint = {"offset": 0, "revision": 0}
        self.batches = []
        self.fail = False

    def state(self, source):
        return copy.deepcopy(self.checkpoint)

    def commit(self, source, expected, mutations, checkpoint):
        if self.fail:
            raise ValueError("simulated transaction failure")
        self.batches.append(mutations)
        self.checkpoint.update(checkpoint, revision=expected["revision"] + 1)


def test_append_partial_record_and_restart_resume(tmp_path):
    src, writer = source(tmp_path), FakeWriter()
    record = json.dumps(catalog("2026-10-23T10:00:00Z"))
    src.path.write_text(record)
    assert poll_source(writer, src)["records"] == 0
    assert writer.checkpoint["offset"] == 0
    with src.path.open("a") as handle:
        handle.write("\n")
    assert poll_source(writer, src)["records"] == 1
    assert poll_source(writer, src)["records"] == 0
    assert len(writer.batches) == 1


def test_invalid_records_and_failed_writes_preserve_cursor(tmp_path):
    src, writer = source(tmp_path), FakeWriter()
    src.path.write_text(json.dumps(catalog("2026-10-23T10:00:00Z")) + "\n")
    writer.fail = True
    with pytest.raises(ValueError, match="transaction failure"):
        poll_source(writer, src)
    assert writer.checkpoint["offset"] == 0
    src.path.write_text('{"unknown": true}\n')
    with pytest.raises(ValueError, match="line 1"):
        poll_source(writer, src)
    assert writer.checkpoint["offset"] == 0


def test_truncation_and_processed_prefix_replacement_are_detected(tmp_path):
    src, writer = source(tmp_path), FakeWriter()
    src.path.write_text(json.dumps(catalog("2026-10-23T10:00:00Z")) + "\n")
    poll_source(writer, src)
    original = src.path.read_bytes()
    src.path.write_bytes(b"x" * len(original))
    with pytest.raises(ValueError, match="bytes changed"):
        poll_source(writer, src)
    src.path.write_text("")
    with pytest.raises(ValueError, match="truncated"):
        poll_source(writer, src)


def test_fingerprint_does_not_read_entire_large_file(tmp_path):
    path = tmp_path / "large"
    path.write_bytes(b"a" * 1_000_000)
    with path.open("rb") as handle:
        handle.seek(123)
        fingerprint(handle, 900_000)
        assert handle.tell() == 123


def test_source_configuration_rejects_duplicate_ids_and_demo_namespace(tmp_path):
    src = source(tmp_path).model_dump(mode="json")
    with pytest.raises(ValueError):
        Sources(namespace="incident-detective-v1", sources=[src])
    with pytest.raises(ValueError):
        Sources(namespace="inputs-test", sources=[src, src])
