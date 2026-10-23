from config import DEMO_ID
from knowledge.queries import LOAD_INCIDENT, KnowledgeRepository


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
    assert query == LOAD_INCIDENT
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


def test_dependency_growth_is_bounded_and_truncation_is_explicit():
    class DenseDatabase:
        def __init__(self):
            self.frontiers = []

        def read(self, query, **params):
            if query == LOAD_INCIDENT:
                return [
                    {
                        "incident": {
                            "affected_component": "root",
                            "timestamp": "2026-10-23T10:42:00Z",
                        }
                    }
                ]
            self.frontiers.append(params["frontier"])
            return [
                {"source": root, "targets": [f"{root}-{n}" for n in range(17)]}
                for root in params["frontier"]
            ]

    db = DenseDatabase()
    paths = KnowledgeRepository(db).dependencies("incident")
    assert len(paths) == 64
    assert len(db.frontiers) == 3
    assert all(len(frontier) <= 64 for frontier in db.frontiers)
    assert all(row["truncated"] and len(row["path"]) <= 4 for row in paths)
    assert len({row["component_id"] for row in paths}) == 64
