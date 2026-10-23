"""Explicit user-confirmed, transactional and idempotent Neo4j memory writes."""

import hashlib
from datetime import UTC, datetime

from config import DEMO_ID

VALIDATE_CAUSE = """
MATCH (i:Incident {id: $incident_id, demo_id: $demo_id})
      -[:AFFECTS]->(root:Component {demo_id: $demo_id})
UNWIND $dependency_paths AS path_ids
WITH i, root, path_ids
WHERE size(path_ids) >= 1 AND size(path_ids) <= 4 AND head(path_ids) = root.id
  AND all(idx IN range(0,size(path_ids)-2) WHERE EXISTS {
    MATCH (a:Component {id:path_ids[idx],demo_id:$demo_id})
          -[r:DEPENDS_ON]->(b:Component {id:path_ids[idx+1],demo_id:$demo_id})
    WHERE (r.valid_from_ms IS NULL OR r.valid_from_ms <= datetime(i.timestamp).epochMillis)
      AND (r.valid_to_ms IS NULL OR datetime(i.timestamp).epochMillis < r.valid_to_ms)
  })
WITH i, collect(DISTINCT last(path_ids)) AS eligible
MATCH (cause {id: $cause_entity_id, demo_id: $demo_id})
WHERE (cause:Component AND cause.id IN eligible) OR
  (cause:Deployment AND datetime(cause.timestamp) <= datetime(i.timestamp)
    AND datetime(cause.timestamp) >= datetime(i.timestamp) - duration({minutes:30})
    AND EXISTS {
      MATCH (cause)-[:CHANGED]->(c:Component {demo_id:$demo_id}) WHERE c.id IN eligible
    })
RETURN i.id AS incident_id, cause.id AS cause_id
"""

STORE_FINDING = """
MATCH (i:Incident {id: $incident_id, demo_id: $demo_id})
MATCH (cause {id: $cause_entity_id, demo_id: $demo_id})
MERGE (f:Finding {id: $finding_id})
ON CREATE SET f.conclusion = $conclusion, f.confirmed = true,
              f.created_at = $created_at, f.demo_id = $demo_id
MERGE (f)-[:EXPLAINS]->(i)
MERGE (f)-[:ATTRIBUTED_TO]->(cause)
RETURN f.id AS finding_id
"""


def confirm_finding(
    database,
    incident_id: str,
    cause_entity_id: str,
    conclusion: str,
    evidence: dict,
    *,
    user_confirmed: bool = False,
) -> str:
    if user_confirmed is not True:
        raise ValueError("A user must explicitly confirm the finding.")
    conclusion = " ".join(conclusion.split())
    if not conclusion or len(conclusion) > 2000:
        raise ValueError("Enter a conclusion between 1 and 2000 characters.")
    if evidence.get("incident", {}).get("id") != incident_id:
        raise ValueError("The finding must refer to the investigated incident.")
    if cause_entity_id not in evidence.get("eligible_cause_ids", []):
        raise ValueError("Cause entity must belong to retrieved current evidence.")
    namespace = evidence["incident"].get("demo_id", DEMO_ID)
    digest = hashlib.sha256(
        f"{namespace}\0{incident_id}\0{cause_entity_id}\0{conclusion}".encode()
    ).hexdigest()[:24]
    finding_id = f"finding-user-{digest}"
    params = {
        "demo_id": namespace,
        "incident_id": incident_id,
        "cause_entity_id": cause_entity_id,
        "dependency_paths": evidence.get("dependency_paths", []),
        "finding_id": finding_id,
        "conclusion": conclusion,
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    def store(tx):
        if not tx.run(VALIDATE_CAUSE, **params).single():
            raise ValueError("Incident or eligible current cause no longer exists in Neo4j.")
        collision = tx.run(
            "MATCH (f:Finding {id: $finding_id}) "
            "WHERE f.demo_id IS NULL OR f.demo_id <> $demo_id RETURN f.id AS id",
            **params,
        ).single()
        if collision:
            raise ValueError("Finding ID belongs to another namespace.")
        return tx.run(STORE_FINDING, **params).single()["finding_id"]

    return database.write_transaction(store)
