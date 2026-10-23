"""Versioned construction contract; Neo4j constraints alone do not enforce an ontology."""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

ONTOLOGY = json.loads(Path(__file__).with_name("ontology.json").read_text())
VERSION = ONTOLOGY["version"]
LABELS = frozenset(ONTOLOGY["entities"])
RELATIONSHIPS = frozenset(ONTOLOGY["relationships"])


def utc(value: str) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError("Timestamps must explicitly use UTC (Z or +00:00).")
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def epoch_ms(value: str) -> int:
    return int(datetime.fromisoformat(utc(value).replace("Z", "+00:00")).timestamp() * 1000)


def validate_node(label: str, properties: dict):
    if label not in LABELS:
        raise ValueError(f"Unknown ontology entity: {label}")
    required = ONTOLOGY["entities"][label]["required"]
    allowed = ONTOLOGY["common_properties"] | required
    if set(properties) - allowed.keys():
        raise ValueError(f"Unknown {label} properties: {set(properties) - allowed.keys()}")
    for key, kind in allowed.items():
        if key not in properties and key not in required:
            continue
        value = properties.get(key)
        expected = {"bool": bool, "int": int}.get(kind, str)
        if type(value) is not expected or (expected is str and not value.strip()):
            raise ValueError(f"{label}.{key} requires {kind}.")
        if kind == "utc":
            utc(value)
    for key, value in properties.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError("Invalid property name")
        if not isinstance(value, str | int | float | bool):
            raise ValueError("Graph properties must be scalar values.")


def validate_edge(kind: str, source_label: str, target_label: str):
    if [source_label, target_label] not in ONTOLOGY["relationships"].get(kind, []):
        raise ValueError(f"Forbidden relationship: {source_label} -{kind}-> {target_label}")


def ensure_schema(database):
    for label in sorted(LABELS | {"IngestionSource"}):
        database.write(
            f"CREATE CONSTRAINT incident_detective_{label.lower()}_id IF NOT EXISTS "
            f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
        )
    for label in ("Deployment", "Symptom"):
        database.write(
            f"CREATE INDEX detective_{label.lower()}_component_time IF NOT EXISTS "
            f"FOR (n:{label}) ON (n.demo_id, n.component_id, n.timestamp_ms)"
        )
    database.write(
        "CREATE INDEX detective_symptom_type_time IF NOT EXISTS "
        "FOR (n:Symptom) ON (n.demo_id, n.type, n.timestamp_ms)"
    )
