"""Stored graph pages must remain scoped, ordered and complete across cursors."""

import os
from unittest.mock import Mock

import pytest

from knowledge.db import Database
from knowledge.explorer import GraphExplorer
from knowledge.temporal_fixture import build_fixture
from knowledge.temporal_seed import seed_temporal


def test_rejects_unknown_label_without_running_a_query():
    database = Mock()
    with pytest.raises(ValueError, match="ontology"):
        GraphExplorer(database).page(label="Component) RETURN n //")
    database.read.assert_not_called()


@pytest.mark.integration
@pytest.mark.skipif(os.getenv("RUN_NEO4J_TESTS") != "1", reason="Requires local Neo4j")
def test_real_pages_retrieve_every_record_without_duplicate_or_unretrieved_edges():
    with Database() as db:
        seed_temporal(db)
        explorer = GraphExplorer(db)
        after, records = "", []
        for _ in range(20):
            page = explorer.page(label="All types", after=after, limit=17)
            graph = page["graph"]
            ids = [n["id"] for n in graph["nodes"]]
            assert ids == sorted(ids)
            assert all(edge["source"] in ids and edge["target"] in ids for edge in graph["edges"])
            records.extend(ids)
            after = page["next_cursor"]
            if after is None:
                break
        else:
            pytest.fail("Pagination did not terminate")
        assert len(records) == len(set(records))
        assert set(records) == {n["id"] for n in build_fixture()["nodes"]}
        selected = explorer.page(search="profile")
        assert {n["name"] for n in selected["graph"]["nodes"]} == {
            "profile-service",
            "profile-cache",
        }
