from types import SimpleNamespace

import pytest

from seed import _seed_transaction, load_fixture


class SeedTransaction:
    def __init__(self, collision=False, cross_namespace=False):
        self.calls = []
        self.collision = collision
        self.cross_namespace = cross_namespace

    def run(self, query, **params):
        assert isinstance(query, str)  # Managed tx.run accepts strings, not neo4j.Query objects.
        self.calls.append((query, params))
        if "n.id IN $ids" in query:
            return SimpleNamespace(data=lambda: [{"id": "collision"}] if self.collision else [])
        if "count(m)" in query:
            return SimpleNamespace(single=lambda: {"count": int(self.cross_namespace)})
        return SimpleNamespace(consume=lambda: None)


def test_load_fixture_valid():
    assert len(load_fixture()["nodes"]) == 37


def test_seed_only_merges_and_scopes(fixture_data):
    tx = SeedTransaction()
    _seed_transaction(tx, fixture_data, False)
    assert all("DELETE" not in q for q, _ in tx.calls)
    assert sum("MERGE (n:" in q for q, _ in tx.calls) == 5
    assert sum("MERGE (a)-" in q for q, _ in tx.calls) == 7
    for q, params in tx.calls:
        if "MERGE (n:" in q:
            assert all(row["demo_id"] == "incident-detective-v1" for row in params["rows"])
        if "MERGE (a)-" in q:
            assert "demo_id: $demo_id" in q


def test_collision_refuses_any_mutations(fixture_data):
    tx = SeedTransaction(collision=True)
    with pytest.raises(ValueError, match="collision"):
        _seed_transaction(tx, fixture_data, True)
    assert all("MERGE" not in q and "DELETE" not in q for q, _ in tx.calls)


def test_reset_refuses_cross_namespace_relationships(fixture_data):
    tx = SeedTransaction(cross_namespace=True)
    with pytest.raises(ValueError, match="cross-namespace"):
        _seed_transaction(tx, fixture_data, True)
    assert all("DELETE" not in q for q, _ in tx.calls)


def test_reset_deletes_only_scoped_demo(fixture_data):
    tx = SeedTransaction()
    _seed_transaction(tx, fixture_data, True)
    deletions = [(q, params) for q, params in tx.calls if "DELETE" in q]
    assert deletions == [
        ("MATCH (n {demo_id: $demo_id}) DETACH DELETE n", {"demo_id": "incident-detective-v1"})
    ]
