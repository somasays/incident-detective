from config import DEMO_ID
from knowledge.queries import DEPENDENCIES, KnowledgeRepository


class RecordingDatabase:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or []

    def read(self, query, **params):
        self.calls.append((query, params))
        return self.result


def test_parameterized_query_and_scope():
    db = RecordingDatabase()
    repo = KnowledgeRepository(db)
    dangerous_id = "INC-104'}) DETACH DELETE n //"
    repo.dependencies(dangerous_id)
    query, params = db.calls[0]
    assert query == DEPENDENCIES
    assert dangerous_id not in query
    assert params == {"demo_id": DEMO_ID, "incident_id": dangerous_id}


def test_all_repository_calls_scoped():
    db = RecordingDatabase()
    repo = KnowledgeRepository(db)
    repo.list_incidents()
    repo.get_incident("INC-104")
    repo.dependencies("INC-104")
    repo.recent_deployments(["analytics-api"], "2026-10-21T10:42:00Z")
    repo.symptoms(["analytics-api"], "2026-10-21T10:42:00Z")
    repo.historical_incidents("INC-104")
    repo.evidence_graph(["analytics-api"])
    assert len(db.calls) == 7
    assert all(params["demo_id"] == DEMO_ID and "$demo_id" in q for q, params in db.calls)


def test_normalize_memory_deduplicates_null_findings():
    past = {
        "id": "INC-092",
        "timestamp": "2026-09-10T09:40:00Z",
        "summary": "Historical regression",
    }
    finding = {"id": "finding-092", "conclusion": "Schema regression"}
    rows = [
        {
            "incident": past,
            "shared_symptoms": ["HTTP_500", "SCHEMA_MISMATCH"],
            "finding": None,
            "causes": [None],
        },
        {
            "incident": past,
            "shared_symptoms": ["SCHEMA_MISMATCH", "HTTP_500"],
            "finding": finding,
            "causes": [None, {"id": "event-connector", "label": "Component"}],
        },
        {
            "incident": past,
            "shared_symptoms": ["SCHEMA_MISMATCH", "HTTP_500"],
            "finding": finding,
            "causes": [],
        },
    ]
    memories = KnowledgeRepository(RecordingDatabase(rows)).historical_incidents("INC-104")
    assert len(memories) == 1
    assert len(memories[0]["confirmed_findings"]) == 1
    assert memories[0]["shared_symptoms"] == ["HTTP_500", "SCHEMA_MISMATCH"]
    assert memories[0]["confirmed_findings"][0]["causes"] == [
        {"id": "event-connector", "label": "Component"}
    ]
