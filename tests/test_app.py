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
