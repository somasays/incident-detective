"""Streamlit's supported test harness verifies reruns do not trigger new inference."""

from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest


class DummyDatabase:
    def __init__(self, *args):
        pass


@pytest.fixture(autouse=True)
def clear_streamlit_cache():
    import streamlit as st

    st.cache_resource.clear()
    yield
    st.cache_resource.clear()


def test_dashboard_investigate_and_rerun(repository, valid_analysis):
    from test_agent import Reasoner

    repository.list_incidents = lambda: [
        repository.get_incident(id) for id in ["INC-104", "INC-105"]
    ]
    reasoner = Reasoner(valid_analysis)
    with (
        patch("knowledge.db.Database", DummyDatabase),
        patch("knowledge.queries.KnowledgeRepository", return_value=repository),
        patch("agent.reasoning.OllamaReasoner", return_value=reasoner),
    ):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
        app.run()
        assert not app.exception
        assert reasoner.calls == 0
        app.button[0].click().run()
        assert not app.exception
        assert reasoner.calls == 1
        app.run()
        assert not app.exception
        assert reasoner.calls == 1
        assert app.session_state["investigations"]["INC-104"]["status"] == "complete"


def test_dashboard_database_unavailable():
    def broken(*args):
        raise ConnectionError("offline")

    with patch("knowledge.db.Database", side_effect=broken):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
        app.run()
        assert not app.exception
        assert any("Neo4j is unavailable" in w.value for w in app.warning)


def test_ontology_view_works_without_database_or_model():
    with patch("knowledge.db.Database", side_effect=AssertionError("Database must not be used")):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
        app.session_state["workspace_view"] = "Ontology"
        app.run()
        assert not app.exception
        assert [metric.value for metric in app.metric] == ["1.0.0", "5", "7", "8"]
        assert app.selectbox[0].value == "Component"
        app.selectbox[0].set_value("Finding").run()
        assert not app.exception


def test_graph_and_ontology_navigation_do_not_repeat_inference(repository, valid_analysis):
    from test_agent import Reasoner

    from config import DEMO_ID

    repository.namespace = DEMO_ID
    repository.list_incidents = lambda: [repository.get_incident("INC-104")]
    repository.graph_page = lambda labels, relationships, **kwargs: {
        "nodes": [n for n in repository.nodes.values() if n["label"] in labels],
        "edges": [e for e in repository.edges if e["type"] in relationships],
        "has_more_nodes": False,
        "has_more_edges": False,
    }
    reasoner = Reasoner(valid_analysis)
    with (
        patch("knowledge.db.Database", DummyDatabase),
        patch("knowledge.queries.KnowledgeRepository", return_value=repository),
        patch("agent.reasoning.OllamaReasoner", return_value=reasoner),
    ):
        app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=20)
        app.run()
        app.button[0].click().run()
        assert reasoner.calls == 1
        app.radio(key="workspace_view").set_value("Knowledge Graph").run()
        assert not app.exception
        assert len(app.selectbox(key="inspect_stored_node_" + DEMO_ID).options) == 37
        app.radio(key="workspace_view").set_value("Ontology").run()
        assert not app.exception
        app.radio(key="workspace_view").set_value("Investigation").run()
        assert not app.exception
        assert reasoner.calls == 1
