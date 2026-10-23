"""Measure indexed retrieval on disposable generated data; this is not a capacity guarantee."""

import argparse
import json
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.models import Source  # noqa: E402
from ingestion.runner import poll_source  # noqa: E402
from ingestion.store import GraphWriter  # noqa: E402
from knowledge.db import Database  # noqa: E402
from knowledge.ontology import ensure_schema, epoch_ms  # noqa: E402
from knowledge.queries import KnowledgeRepository  # noqa: E402
from scripts.create_ingestion_example import append, catalog, trace_export  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--noise", type=int, default=10_000)
    parser.add_argument("--output", type=Path, default=Path("artifacts/scale-check.json"))
    args = parser.parse_args()
    if not 1 <= args.noise <= 100_000:
        parser.error("--noise must be 1..100000")
    namespace = "inputs-benchmark-" + uuid.uuid4().hex[:12]
    at = "2026-10-23T10:42:00Z"
    results = []
    with Database() as db, tempfile.TemporaryDirectory() as temporary:
        ensure_schema(db)
        writer = GraphWriter(db, namespace)
        try:
            for adapter, record in [
                ("catalog", catalog("2026-10-23T10:00:00Z")),
                ("otlp", trace_export()),
                (
                    "incidents",
                    {
                        "id": "bench-alert",
                        "service": "web-api",
                        "timestamp": at,
                        "summary": "Benchmark",
                        "severity": "SEV-1",
                        "status": "open",
                    },
                ),
            ]:
                path = Path(temporary) / f"{adapter}.jsonl"
                append(path, record)
                poll_source(
                    writer, Source(id=adapter, adapter=adapter, path=path, environment="local")
                )
            repo = KnowledgeRepository(db, namespace)
            incident = repo.list_incidents()[0]
            component = incident["affected_component"]

            def measure(noise):
                timings = []
                for _ in range(6):
                    start = time.perf_counter()
                    paths = repo.dependencies(incident["id"])
                    components = [p["component_id"] for p in paths]
                    deployments = repo.recent_deployments(components, at)
                    symptoms = repo.symptoms(components, at)
                    memories = repo.historical_incidents(incident["id"])
                    repo.evidence_graph([incident["id"], *components], at)
                    timings.append((time.perf_counter() - start) * 1000)
                return {
                    "old_symptoms": noise,
                    "median_retrieval_ms": round(statistics.median(timings[1:]), 2),
                    "components_returned": len(paths),
                    "symptoms_returned": len(symptoms),
                    "deployments_returned": len(deployments),
                    "memories_returned": len(memories),
                }

            results.append(measure(0))
            for start in range(0, args.noise, 1000):
                db.write(
                    "MATCH (c:Component {id:$component}) UNWIND range($start,$end) AS i "
                    "CREATE (s:Symptom {id:$ns+':old:'+toString(i),demo_id:$ns, "
                    "component_id:$component,timestamp_ms:$old, "
                    "timestamp:'2026-10-22T10:00:00Z',type:'HTTP_500',message:'old noise'}) "
                    "CREATE (s)-[:OBSERVED_ON]->(c)",
                    component=component,
                    ns=namespace,
                    start=start,
                    end=min(start + 999, args.noise - 1),
                    old=epoch_ms("2026-10-22T10:00:00Z"),
                )
            results.append(measure(args.noise))
            # Separately exercise a dense root: fan-out must be capped and reported.
            db.write(
                "MATCH (c:Component {id:$component}) UNWIND range(1,100) AS i "
                "CREATE (d:Component {id:$ns+':fanout:'+toString(i),demo_id:$ns, "
                "name:'fanout',type:'service',description:'stress test'}) "
                "CREATE (c)-[:DEPENDS_ON]->(d)",
                component=component,
                ns=namespace,
            )
            dense = repo.dependencies(incident["id"])
            assert len(dense) <= 64 and all(r["truncated"] for r in dense)
            result = {
                "measurements": results,
                "dense_root": {
                    "outgoing_dependencies_added": 100,
                    "components_returned": len(dense),
                    "truncation_reported": True,
                },
                "scope": (
                    "Warm local retrieval only; generated history; "
                    "no LLM or ingestion throughput claim."
                ),
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2))
            print(json.dumps(result, indent=2))
        finally:
            # Only disposable data created by this invocation is removed.
            db.write("MATCH (n {demo_id:$ns}) DETACH DELETE n", ns=namespace)


if __name__ == "__main__":
    main()
