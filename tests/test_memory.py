from types import SimpleNamespace

import pytest

from knowledge.memory import confirm_finding


class MemoryDatabase:
    """Transactional write double; real Neo4j behavior is covered in test_integration.py."""

    def __init__(self):
        self.findings = {}
        self.relationships = set()
        self.queries = []
        self.exists = True

    def write_transaction(self, callback):
        return callback(self)

    def run(self, query, **params):
        text = str(query)
        self.queries.append((text, params))
        if "eligible" in text:
            return SimpleNamespace(
                single=lambda: {"cause_id": params["cause_entity_id"]} if self.exists else None
            )
        if "WHERE f.demo_id IS NULL" in text:
            return SimpleNamespace(single=lambda: None)
        id = params["finding_id"]
        self.findings.setdefault(id, params)
        self.relationships.add((id, "EXPLAINS", params["incident_id"]))
        self.relationships.add((id, "ATTRIBUTED_TO", params["cause_entity_id"]))
        return SimpleNamespace(single=lambda: {"finding_id": id})


def test_confirmation_idempotent(evidence):
    db = MemoryDatabase()
    first = confirm_finding(
        db, "INC-104", "deploy-014", "Verified schema change", evidence, user_confirmed=True
    )
    second = confirm_finding(
        db, "INC-104", "deploy-014", "  Verified  schema change  ", evidence, user_confirmed=True
    )
    assert first == second
    assert len(db.findings) == 1
    assert db.relationships == {
        (first, "EXPLAINS", "INC-104"),
        (first, "ATTRIBUTED_TO", "deploy-014"),
    }


@pytest.mark.parametrize(
    "incident,cause,conclusion,confirmed",
    [
        ("INC-104", "deploy-014", "Verified", False),
        ("INC-104", "deploy-014", "   ", True),
        ("INC-104", "deploy-016", "Verified", True),
        ("INC-105", "deploy-014", "Verified", True),
    ],
)
def test_confirmation_validation(evidence, incident, cause, conclusion, confirmed):
    db = MemoryDatabase()
    with pytest.raises(ValueError):
        confirm_finding(db, incident, cause, conclusion, evidence, user_confirmed=confirmed)
    assert not db.queries


def test_entity_deleted_after_retrieval(evidence):
    db = MemoryDatabase()
    db.exists = False
    with pytest.raises(ValueError, match="no longer exists"):
        confirm_finding(db, "INC-104", "deploy-014", "Verified", evidence, user_confirmed=True)
    assert not db.findings
