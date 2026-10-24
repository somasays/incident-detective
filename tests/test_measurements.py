"""Both retrieval paths must compare the same windows and preserve source evidence."""

from copy import deepcopy

from knowledge.diagnostic_tools import empty_package, merge_evidence
from knowledge.measurements import measurement_rows
from knowledge.temporal_queries import TemporalRepository

REQUEST = {"effectiveAt": "2026-10-23T01:00:00Z"}


def observation(id, start, end, value, *, dimensions=(), metric="latency"):
    return {
        "id": id,
        "kind": "metric_window",
        "entityId": "service",
        "metricName": metric,
        "unit": "ms",
        "aggregation": "p95",
        "dimensions": list(dimensions),
        "windowStart": f"2026-10-23T{start}:00Z",
        "windowEnd": f"2026-10-23T{end}:00Z",
        "value": value,
        "sampleCount": 100,
    }


def test_dimension_order_and_input_order_do_not_change_window_selection():
    observations = [
        observation("before", "00:15", "00:25", 10, dimensions=("zone=a", "status=ok")),
        observation("during-old", "00:45", "00:50", 30, dimensions=("status=ok", "zone=a")),
        observation("during", "00:55", "01:00", 50, dimensions=("zone=a", "status=ok")),
        observation("after", "01:15", "01:20", 12, dimensions=("status=ok", "zone=a")),
    ]
    original = deepcopy(observations)
    rows = measurement_rows(observations, REQUEST)
    assert rows == measurement_rows(list(reversed(observations)), REQUEST)
    assert observations == original
    assert len(rows) == 1
    assert rows[0]["evidenceIds"] == {
        "baseline": "before", "incident": "during", "recovery": "after"
    }
    assert rows[0]["difference"] == 40
    assert rows[0]["ratio"] == 5


def test_zero_reference_does_not_divide_by_zero_or_merge_distinct_dimensions():
    observations = [
        observation("before", "00:15", "00:25", 0, dimensions=("zone=a",)),
        observation("during", "00:55", "01:00", 50, dimensions=("zone=a",)),
        observation("other-zone", "00:55", "01:00", 80, dimensions=("zone=b",)),
    ]
    rows = measurement_rows(observations, REQUEST)
    assert len(rows) == 2
    assert rows[0]["ratio"] is None
    assert rows[0]["difference"] == 50
    assert "baseline" not in rows[1]


def test_evidence_and_incremental_paths_share_measurement_calculation(monkeypatch):
    observations = [
        observation("before", "00:15", "00:25", 10),
        observation("during", "00:55", "01:00", 50),
    ]

    class Database:
        def read(self, query, **params):
            if "AS entityId" in query and "Observation" in query:
                return [
                    {
                        "node": {**o, "label": "Observation"},
                        "entityId": "service",
                        "edge": {
                            "id": "edge-" + o["id"],
                            "source": o["id"],
                            "target": "service",
                            "type": "OBSERVED_ON",
                        },
                    }
                    for o in observations
                ]
            return []

    monkeypatch.setattr(
        TemporalRepository, "read", lambda self, name, query, **p: Database().read(query, **p)
    )
    repository = TemporalRepository(Database())
    topology = {"nodes": [{"id": "service", "label": "Component"}], "edges": [], "paths": []}
    request = {**REQUEST, "knowledgeAsOf": REQUEST["effectiveAt"]}
    collected = repository.collect(request, topology)
    merged = merge_evidence(empty_package(request), {"observations": observations})
    assert collected["measurements"] == merged["measurements"]
    assert collected["measurements"][0]["incident"] == 50
