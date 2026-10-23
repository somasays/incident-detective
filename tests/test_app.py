"""Temporal workspace reruns, navigation and unavailable-model behavior."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from knowledge.temporal_fixture import build_fixture
from knowledge.temporal_seed import spec


class DummyDatabase:
    def __init__(self, *args):
        pass

    def read(self, query, **params):
        if "AS edge" in query:
            return []
        return [{"node": n} for n in build_fixture()["nodes"] if n["label"] == "Component"]


class Repository:
    def __init__(self, db):
        self.database = db
        self.nodes = {n["label"]: n for n in spec()["nodes"].values()}

    def catalog(self):
        return [n for n in build_fixture()["nodes"] if n["label"] in {"Component", "System"}]

    def topology(self, request, max_depth=1):
        root = next(n for n in self.catalog() if n["id"] == request["rootId"])
        return {"nodes": [root], "edges": [], "paths": [[root["id"]]]}

    trace = []

    def observe_target(self, request, ids):
        root = request["rootId"]
        return [
            {
                "observation": {
                    "id": "test-metric",
                    "label": "Observation",
                    "kind": "metric_window",
                    "entityId": root,
                    "metricName": "latency",
                    "value": 88,
                    "unit": "ms",
                    "aggregation": "p95",
                    "windowStart": "2026-10-23T07:55:00Z",
                    "windowEnd": "2026-10-23T08:00:00Z",
                },
                "edge": {
                    "id": "test-edge",
                    "type": "OBSERVED_ON",
                    "source": "test-metric",
                    "target": root,
                },
            }
        ]

    def find_precedents(self, request, topology, signals):
        return []

    def collect(self, request, topology):
        return {
            "request": request,
            "topology": topology,
            "graph": deepcopy(topology),
            "index": {n["id"]: n for n in topology["nodes"]},
            "measurements": [],
            "changes": [],
            "observations": [],
            "states": [],
            "historicalFindings": [],
            "limitations": [],
            "queryTrace": [],
        }


class Reasoner:
    calls = 0

    def check_model(self):
        pass

    def generate(self, messages, schema, timeout_seconds=None):
        import json

        self.calls += 1
        return json.dumps(
            {
                "summary": "No degradation in this small test fixture.",
                "symptom_status": "not_observed",
                "hypotheses": [],
                "next_check": None,
            }
        )


@pytest.fixture(autouse=True)
def clear_streamlit_cache():
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def app_test():
    return AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)


def test_temporal_workspace_is_only_workspace_and_reruns_do_not_infer():
    reasoner = Reasoner()
    with (
        patch("ui.temporal_workspace.Database", DummyDatabase),
        patch("ui.temporal_workspace.TemporalRepository", Repository),
        patch("ui.temporal_workspace.get_temporal_reasoner", return_value=reasoner),
    ):
        app = app_test().run()
        assert not app.exception
        assert app.radio(key="temporal_page").options == [
            "Investigate",
            "Ontology",
            "Knowledge graph",
        ]
        assert reasoner.calls == 0
        next(b for b in app.button if b.label == "Investigate →").click().run()
        assert not app.exception
        assert reasoner.calls == 1
        assert app.session_state["temporal_result"]["status"] == "symptom_not_observed"
        app.run()
        app.radio(key="temporal_page").set_value("Ontology").run()
        assert not app.exception
        app.radio(key="temporal_page").set_value("Knowledge graph").run()
        assert not app.exception
        app.radio(key="temporal_page").set_value("Investigate").run()
        assert not app.exception
        assert reasoner.calls == 1


def test_database_unavailable_has_recovery_command():
    with patch("ui.temporal_workspace.Database", side_effect=ConnectionError("offline")):
        app = app_test().run()
        assert not app.exception
        assert any("Neo4j is unavailable" in error.value for error in app.error)


def test_ontology_works_without_database_or_model():
    with patch("ui.temporal_workspace.Database", side_effect=AssertionError("Must not connect")):
        app = app_test()
        app.session_state["temporal_page"] = "Ontology"
        app.run()
        assert not app.exception
        assert "Observation" in app.selectbox(key="ontology_type").options
        app.selectbox(key="ontology_type").set_value("StateSnapshot").run()
        assert not app.exception


def test_model_failure_preserves_evidence():
    reasoner = Reasoner()
    reasoner.generate = lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("offline"))
    with (
        patch("ui.temporal_workspace.Database", DummyDatabase),
        patch("ui.temporal_workspace.TemporalRepository", Repository),
        patch("ui.temporal_workspace.get_temporal_reasoner", return_value=reasoner),
    ):
        app = app_test().run()
        next(b for b in app.button if b.label == "Investigate →").click().run()
        assert not app.exception
        package = app.session_state["temporal_result"]
        assert package["status"] == "unavailable"
        assert package["graph"]["nodes"]
        assert not package["analysisAvailable"]
