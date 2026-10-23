"""Validated, namespace-scoped, idempotent v2 fixture import into local Neo4j."""

import json
from collections import Counter

from knowledge.temporal_fixture import DATASET, FIXTURE, ONTOLOGY, instant


def spec():
    return json.loads(ONTOLOGY.read_text())


def validate_fixture(fixture):
    ontology = spec()
    definitions = {n["label"]: n for n in ontology["nodes"].values()}
    endpoint_specs = {
        (
            r["type"],
            ontology["nodes"][r["from"]["node"]]["label"],
            ontology["nodes"][r["to"]["node"]]["label"],
        ): r
        for r in ontology["relationships"].values()
    }
    nodes = {n["id"]: n for n in fixture["nodes"]}
    if fixture["datasetId"] != DATASET or len(nodes) != len(fixture["nodes"]):
        raise ValueError("Wrong dataset or duplicate node IDs")

    def properties(record, definition, structural):
        props = definition["properties"]
        if set(record) - set(props) - structural:
            raise ValueError(f"Undeclared properties on {record['id']}")
        for key, field in props.items():
            if field.get("must_exist") and key not in record:
                raise ValueError(f"Missing {record['id']}.{key}")
            if key not in record:
                continue
            value, kind = record[key], field["type"]
            if kind == "ZONED DATETIME":
                if not isinstance(value, str) or not value.endswith("Z"):
                    raise ValueError("Fixture times must be explicit UTC")
                instant(value)
            elif kind == "LIST<STRING>":
                if not isinstance(value, list) or any(type(v) is not str for v in value):
                    raise ValueError(f"Expected string list: {key}")
            elif (
                type(value)
                is not {"STRING": str, "INTEGER": int, "FLOAT": float, "BOOLEAN": bool}[kind]
            ):
                raise ValueError(f"Wrong type: {record['id']}.{key}")
        for start, end in [
            ("validFrom", "validTo"),
            ("recordedAt", "supersededAt"),
            ("windowStart", "windowEnd"),
        ]:
            if start in record and end in record and instant(record[start]) >= instant(record[end]):
                raise ValueError("Invalid temporal interval")

    for node in nodes.values():
        if not node["id"].startswith(DATASET + ":") or node["datasetId"] != DATASET:
            raise ValueError("Unscoped node")
        properties(node, definitions[node["label"]], {"label"})
        if node["label"] == "CodeArtifact":
            if len(node["content"].splitlines()) != node["lineEnd"] - node["lineStart"] + 1:
                raise ValueError("Code line provenance mismatch")
    if len({e["id"] for e in fixture["relationships"]}) != len(fixture["relationships"]):
        raise ValueError("Duplicate relationship IDs")
    for edge in fixture["relationships"]:
        source, target = nodes[edge["source"]], nodes[edge["target"]]
        definition = endpoint_specs[(edge["type"], source["label"], target["label"])]
        properties(edge, definition, {"type", "source", "target"})
    return fixture


def typed(record, definition, exclude=()):
    return {
        key: instant(value) if definition["properties"][key]["type"] == "ZONED DATETIME" else value
        for key, value in record.items()
        if key not in exclude
    }


def seed_temporal(database, fixture=None):
    fixture = validate_fixture(fixture or json.loads(FIXTURE.read_text()))
    ontology = spec()
    labels = {n["label"]: n for n in ontology["nodes"].values()}
    # Community uses uniqueness constraints; field types/existence are validated above.
    for label in labels:
        database.write(
            f"CYPHER 25 CREATE CONSTRAINT sre_v2_{label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )

    def work(tx):
        for label, definition in labels.items():
            rows = [
                typed(n, definition, {"label"}) for n in fixture["nodes"] if n["label"] == label
            ]
            if not rows:
                continue
            conflict = tx.run(
                f"CYPHER 25 MATCH (n:{label}) WHERE n.id IN $ids "
                "AND (n.datasetId IS NULL OR n.datasetId <> $dataset "
                "OR n.recordHash <> $hashes[n.id]) RETURN n.id AS id LIMIT 1",
                ids=[r["id"] for r in rows],
                dataset=DATASET,
                hashes={r["id"]: r["recordHash"] for r in rows},
            ).single()
            if conflict:
                raise ValueError("Seed collision or changed immutable fixture; use a new dataset.")
            query = f"CYPHER 25 UNWIND $rows AS row MERGE (n:{label} {{id:row.id}}) "
            query += "ON CREATE SET n += row"
            tx.run(query.replace("CYPHER 25", "CYPHER 25 EXPLAIN", 1), rows=rows).consume()
            tx.run(query, rows=rows).consume()
        for definition in ontology["relationships"].values():
            kind = definition["type"]
            source = ontology["nodes"][definition["from"]["node"]]["label"]
            target = ontology["nodes"][definition["to"]["node"]]["label"]
            rows = [
                {
                    "source": e["source"],
                    "target": e["target"],
                    "properties": typed(e, definition, {"source", "target", "type"}),
                }
                for e in fixture["relationships"]
                if e["type"] == kind
                and next(n for n in fixture["nodes"] if n["id"] == e["source"])["label"] == source
                and next(n for n in fixture["nodes"] if n["id"] == e["target"])["label"] == target
            ]
            if not rows:
                continue
            query = (
                f"CYPHER 25 UNWIND $rows AS row MATCH (a:{source} "
                "{id:row.source,datasetId:$dataset}) "
                f"MATCH (b:{target} {{id:row.target,datasetId:$dataset}}) "
                f"MERGE (a)-[r:{kind} {{id:row.properties.id}}]->(b) "
                "ON CREATE SET r += row.properties RETURN count(r) AS count"
            )
            tx.run(
                query.replace("CYPHER 25", "CYPHER 25 EXPLAIN", 1), rows=rows, dataset=DATASET
            ).consume()
            if tx.run(query, rows=rows, dataset=DATASET).single()["count"] != len(rows):
                raise ValueError("Missing relationship endpoint; transaction rolled back")

    database.write_transaction(work)
    for label in labels:
        database.write(
            f"CYPHER 25 CREATE INDEX sre_v2_{label.lower()}_dataset IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.datasetId, n.recordedAt)"
        )
    database.write("CYPHER 25 CALL db.awaitIndexes(30)")
    return {
        "datasetId": DATASET,
        "nodes": len(fixture["nodes"]),
        "relationships": len(fixture["relationships"]),
        "labels": dict(Counter(n["label"] for n in fixture["nodes"])),
    }
