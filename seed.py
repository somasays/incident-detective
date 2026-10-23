"""Idempotently seed only this demo namespace. Never clear unrelated Neo4j data."""

import argparse
import json
from pathlib import Path

from config import DEMO_ID
from knowledge.ontology import LABELS, RELATIONSHIPS, ensure_schema, epoch_ms

FIXTURE_PATH = Path(__file__).parent / "data" / "scenarios.json"


def load_fixture(path: Path = FIXTURE_PATH):
    fixture = json.loads(path.read_text())
    if fixture["demo_id"] != DEMO_ID:
        raise ValueError("Fixture demo namespace does not match this application.")
    nodes = fixture["nodes"]
    ids = {n["id"] for n in nodes}
    if len(ids) != len(nodes) or any(n["label"] not in LABELS for n in nodes):
        raise ValueError("Invalid or duplicate fixture nodes.")
    for e in fixture["edges"]:
        if e["type"] not in RELATIONSHIPS or e["source"] not in ids or e["target"] not in ids:
            raise ValueError("Invalid fixture relationship.")
    return fixture


def _seed_transaction(tx, fixture, reset):
    # Reject collisions before changing anything, even when reset was requested.
    for label in sorted(LABELS):
        ids = [n["id"] for n in fixture["nodes"] if n["label"] == label]
        collisions = tx.run(
            f"MATCH (n:{label}) WHERE n.id IN $ids "
            "AND (n.demo_id IS NULL OR n.demo_id <> $demo_id) RETURN n.id AS id",
            ids=ids,
            demo_id=DEMO_ID,
        ).data()
        if collisions:
            raise ValueError(f"Seed ID collision with non-demo {label}: {collisions}")
    if reset:
        # Never detach relationships to another namespace: refuse instead.
        cross = tx.run(
            "MATCH (n {demo_id: $demo_id})--(m) "
            "WHERE m.demo_id IS NULL OR m.demo_id <> $demo_id RETURN count(m) AS count",
            demo_id=DEMO_ID,
        ).single()["count"]
        if cross:
            raise ValueError("Demo has cross-namespace relationships; refusing reset.")
        tx.run("MATCH (n {demo_id: $demo_id}) DETACH DELETE n", demo_id=DEMO_ID).consume()
    for label in sorted(LABELS):
        rows = [
            {k: v for k, v in n.items() if k != "label"} | {"demo_id": DEMO_ID}
            for n in fixture["nodes"]
            if n["label"] == label
        ]
        for row in rows:
            if "timestamp" in row:
                row["timestamp_ms"] = epoch_ms(row["timestamp"])
            if label in {"Deployment", "Symptom"}:
                relationship = "CHANGED" if label == "Deployment" else "OBSERVED_ON"
                row["component_id"] = next(
                    e["target"]
                    for e in fixture["edges"]
                    if e["source"] == row["id"] and e["type"] == relationship
                )
        tx.run(
            f"UNWIND $rows AS row MERGE (n:{label} {{id: row.id}}) SET n += row",
            rows=rows,
        ).consume()
    for rel in sorted(RELATIONSHIPS):
        rows = [e for e in fixture["edges"] if e["type"] == rel]
        tx.run(
            "UNWIND $rows AS row "
            "MATCH (a {id: row.source, demo_id: $demo_id}) "
            "MATCH (b {id: row.target, demo_id: $demo_id}) "
            f"MERGE (a)-[:{rel}]->(b)",
            rows=rows,
            demo_id=DEMO_ID,
        ).consume()


def seed(database, fixture=None, reset=False):
    fixture = fixture or load_fixture()
    ensure_schema(database)
    database.write_transaction(_seed_transaction, fixture, reset)
    return {"nodes": len(fixture["nodes"]), "relationships": len(fixture["edges"])}


def main():
    from knowledge.db import Database

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset-demo", action="store_true", help="Reset only the demo namespace")
    args = parser.parse_args()
    with Database() as db:
        db.wait_ready()
        counts = seed(db, reset=args.reset_demo)
        print(f"Seeded {counts['nodes']} nodes / {counts['relationships']} relationships.")
        print("Open incidents: INC-104 and INC-105. All operational data is synthetic.")


if __name__ == "__main__":
    main()
