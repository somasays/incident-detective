"""Fixed parameterized Cypher. Model output never becomes a database query."""

import json

from config import DEMO_ID
from knowledge.bounds import (
    MAX_COMPONENTS,
    MAX_DEPLOYMENTS,
    MAX_DEPTH,
    MAX_MEMORY_CANDIDATES,
    MAX_MEMORY_TYPES,
    MAX_NEIGHBORS,
    MAX_SYMPTOMS,
)
from knowledge.ontology import LABELS, RELATIONSHIPS

BROWSE_NODES = {
    label: f"MATCH (n:{label} {{demo_id:$demo_id}}) WHERE n.id > $after_id "
    "RETURN n{.*, label:head(labels(n))} AS node ORDER BY n.id LIMIT $limit"
    for label in LABELS
}
BROWSE_EDGES = {
    label: f"UNWIND $source_ids AS source_id MATCH (n:{label} {{id:source_id,demo_id:$demo_id}}) "
    "CALL (n) { "
    "MATCH (n)-[r]->(m {demo_id:$demo_id}) "
    "WHERE m.id IN $entity_ids AND type(r) IN $relationship_types "
    "AND (type(r) <> 'DEPENDS_ON' OR $at IS NULL OR "
    " ((r.valid_from_ms IS NULL OR r.valid_from_ms <= $at) AND "
    "  (r.valid_to_ms IS NULL OR $at < r.valid_to_ms))) "
    "RETURN r,m ORDER BY type(r),m.id,elementId(r) LIMIT $limit } "
    "RETURN {source:n.id,target:m.id,type:type(r),properties:properties(r), "
    "native_id:elementId(r)} AS edge "
    "ORDER BY n.id,type(r),m.id,elementId(r) LIMIT $limit"
    for label in LABELS
}

LIST_INCIDENTS = """
MATCH (i:Incident {demo_id: $demo_id})-[:AFFECTS]->(c:Component {demo_id: $demo_id})
WHERE i.status = 'open'
RETURN i{.*, affected_component: c.id, affected_name: c.name} AS incident
ORDER BY i.id
LIMIT 200
"""

LOAD_INCIDENT = """
MATCH (i:Incident {id: $incident_id, demo_id: $demo_id})
      -[:AFFECTS]->(c:Component {demo_id: $demo_id})
RETURN i{.*, affected_component: c.id, affected_name: c.name} AS incident
"""

DEPENDENCIES = """
UNWIND $frontier AS root_id
MATCH (root:Component {id:root_id, demo_id:$demo_id})
CALL (root) {
  MATCH (root)-[r:DEPENDS_ON]->(next:Component {demo_id:$demo_id})
  WHERE (r.valid_from_ms IS NULL OR r.valid_from_ms <= $at)
    AND (r.valid_to_ms IS NULL OR $at < r.valid_to_ms)
  RETURN DISTINCT next.id AS id ORDER BY id LIMIT $neighbor_limit
}
RETURN root.id AS source, collect(id) AS targets
ORDER BY source
"""

RECENT_DEPLOYMENTS = """
MATCH (d:Deployment {demo_id: $demo_id})
WHERE d.component_id IN $component_ids AND d.timestamp_ms <= $at
  AND d.timestamp_ms >= $since
MATCH (d)-[:CHANGED]->(c:Component {demo_id:$demo_id})
WHERE c.id = d.component_id
RETURN d.id AS deployment_id, d.timestamp AS deployed_at, d.description AS description,
       d.version AS version, c.id AS component_id
ORDER BY deployed_at DESC, deployment_id, component_id
LIMIT $limit
"""

RECENT_SYMPTOMS = """
MATCH (s:Symptom {demo_id: $demo_id})
WHERE s.component_id IN $component_ids AND s.timestamp_ms <= $at
  AND s.timestamp_ms >= $since
MATCH (s)-[:OBSERVED_ON]->(c:Component {demo_id:$demo_id})
WHERE c.id = s.component_id
RETURN s.id AS symptom_id, s.timestamp AS observed_at, s.type AS symptom_type,
       s.message AS message, c.id AS component_id
ORDER BY observed_at, symptom_id, component_id
LIMIT $limit
"""

HISTORICAL_INCIDENTS = """
MATCH (current:Incident {id: $incident_id, demo_id: $demo_id})
      -[:HAS_SYMPTOM]->(s:Symptom {demo_id: $demo_id})
WITH DISTINCT current, s.type AS symptom_type ORDER BY symptom_type LIMIT $type_limit
CALL (current, symptom_type) {
  MATCH (old:Symptom {demo_id:$demo_id, type:symptom_type})
  WHERE old.timestamp_ms < current.timestamp_ms
  MATCH (past:Incident {demo_id:$demo_id})-[:HAS_SYMPTOM]->(old)
  WHERE past.id <> current.id AND past.timestamp_ms < current.timestamp_ms
  RETURN past ORDER BY past.timestamp_ms DESC, past.id LIMIT $candidate_limit
}
WITH current, past, collect(DISTINCT symptom_type) AS shared_symptoms
ORDER BY size(shared_symptoms) DESC, past.timestamp DESC, past.id
LIMIT 5
OPTIONAL MATCH (f:Finding {demo_id: $demo_id, confirmed: true})-[:EXPLAINS]->(past)
WHERE datetime(f.created_at) <= datetime(current.timestamp)
OPTIONAL MATCH (f)-[:ATTRIBUTED_TO]->(cause {demo_id: $demo_id})
WHERE cause:Component OR cause:Deployment
RETURN past{.*} AS incident, shared_symptoms, f{.*} AS finding,
       collect(DISTINCT cause{.*, label: head(labels(cause))}) AS causes
ORDER BY size(shared_symptoms) DESC, incident.timestamp DESC, incident.id, finding.id
"""

EVIDENCE_GRAPH = """
UNWIND $entity_ids AS entity_id
CALL (entity_id) {
  MATCH (n:Component {id:entity_id,demo_id:$demo_id}) RETURN n
  UNION
  MATCH (n:Deployment {id:entity_id,demo_id:$demo_id}) RETURN n
  UNION
  MATCH (n:Incident {id:entity_id,demo_id:$demo_id}) RETURN n
  UNION
  MATCH (n:Symptom {id:entity_id,demo_id:$demo_id}) RETURN n
  UNION
  MATCH (n:Finding {id:entity_id,demo_id:$demo_id}) RETURN n
}
OPTIONAL MATCH (n)-[r:DEPENDS_ON|CHANGED|AFFECTS|HAS_SYMPTOM|OBSERVED_ON|EXPLAINS|ATTRIBUTED_TO]
               ->(m {demo_id: $demo_id})
WHERE m.id IN $entity_ids
  AND (type(r) <> 'DEPENDS_ON' OR $at IS NULL OR
      ((r.valid_from_ms IS NULL OR r.valid_from_ms <= $at) AND
       (r.valid_to_ms IS NULL OR $at < r.valid_to_ms)))
RETURN n{.*, label: head(labels(n))} AS node,
       collect(DISTINCT CASE WHEN r IS NOT NULL
         THEN {source: n.id, target: m.id, type: type(r), properties: properties(r)}
         ELSE null END) AS edges
ORDER BY node.id
"""


class KnowledgeRepository:
    def __init__(self, database, namespace=None):
        self.database = database
        self.namespace = namespace or DEMO_ID

    def _read(self, query, **params):
        return self.database.read(query, demo_id=self.namespace, **params)

    def list_incidents(self):
        return [r["incident"] for r in self._read(LIST_INCIDENTS)]

    def list_namespaces(self):
        return [
            DEMO_ID,
            *[
                r["namespace"]
                for r in self.database.read(
                    "MATCH (s:IngestionSource) WHERE s.demo_id STARTS WITH 'inputs-' "
                    "RETURN DISTINCT s.demo_id AS namespace ORDER BY namespace LIMIT 32"
                )
            ],
        ]

    def ingestion_status(self):
        return self._read(
            "MATCH (s:IngestionSource {demo_id:$demo_id}) "
            "RETURN s.source_id AS source, s.adapter AS adapter, s.path AS path, "
            "s.offset AS committed_bytes, s.records AS records, s.updated_at AS last_commit "
            "ORDER BY source LIMIT 32"
        )

    def graph_page(
        self,
        labels,
        relationship_types,
        *,
        after_id="",
        node_limit=100,
        edge_limit=400,
        incident_time=None,
    ):
        """Keyset-paginated instance view with scoped queries and bounded returned records."""
        from knowledge.ontology import epoch_ms

        if not set(labels) <= LABELS or not set(relationship_types) <= RELATIONSHIPS:
            raise ValueError("Unknown ontology label or relationship type.")
        if not 1 <= node_limit <= 200 or not 1 <= edge_limit <= 1000:
            raise ValueError("Graph display budget exceeded.")
        candidates = [
            row["node"]
            for label in sorted(set(labels))
            for row in self._read(BROWSE_NODES[label], after_id=after_id, limit=node_limit + 1)
        ]
        candidates.sort(key=lambda n: n["id"])
        nodes = candidates[:node_limit]
        ids = [n["id"] for n in nodes]
        edges = []
        for label in sorted(set(labels)):
            source_ids = [n["id"] for n in nodes if n["label"] == label]
            if source_ids and relationship_types:
                edges.extend(
                    row["edge"]
                    for row in self._read(
                        BROWSE_EDGES[label],
                        source_ids=source_ids,
                        entity_ids=ids,
                        relationship_types=sorted(set(relationship_types)),
                        limit=edge_limit + 1,
                        at=epoch_ms(incident_time) if incident_time else None,
                    )
                )
        edges.sort(key=lambda e: (e["source"], e["type"], e["target"], e["native_id"]))
        return {
            "nodes": nodes,
            "edges": edges[:edge_limit],
            "has_more_nodes": len(candidates) > node_limit,
            "has_more_edges": len(edges) > edge_limit,
        }

    def get_incident(self, incident_id):
        rows = self._read(LOAD_INCIDENT, incident_id=incident_id)
        return rows[0]["incident"] if rows else None

    def dependencies(self, incident_id):
        from knowledge.ontology import epoch_ms

        incident = self.get_incident(incident_id)
        if not incident:
            return []
        root = incident["affected_component"]
        paths, frontier, truncated = {root: [root]}, [root], False
        for _ in range(MAX_DEPTH):
            if not frontier:
                break
            next_frontier = []
            rows = self._read(
                DEPENDENCIES,
                frontier=frontier,
                at=epoch_ms(incident["timestamp"]),
                neighbor_limit=MAX_NEIGHBORS + 1,
            )
            for row in rows:
                targets = row["targets"]
                truncated |= len(targets) > MAX_NEIGHBORS
                for target in targets[:MAX_NEIGHBORS]:
                    if target in paths:
                        continue
                    if len(paths) >= MAX_COMPONENTS:
                        truncated = True
                        continue
                    paths[target] = paths[row["source"]] + [target]
                    next_frontier.append(target)
            frontier = next_frontier
        return [
            {"path": path, "component_id": component, "truncated": truncated}
            for component, path in sorted(paths.items())
        ]

    def recent_deployments(self, component_ids, incident_time):
        from knowledge.ontology import epoch_ms

        at = epoch_ms(incident_time)
        return self._read(
            RECENT_DEPLOYMENTS,
            component_ids=component_ids,
            at=at,
            since=at - 30 * 60_000,
            limit=MAX_DEPLOYMENTS,
        )

    def symptoms(self, component_ids, incident_time):
        from knowledge.ontology import epoch_ms

        at = epoch_ms(incident_time)
        return self._read(
            RECENT_SYMPTOMS,
            component_ids=component_ids,
            at=at,
            since=at - 30 * 60_000,
            limit=MAX_SYMPTOMS,
        )

    def historical_incidents(self, incident_id):
        rows = self._read(
            HISTORICAL_INCIDENTS,
            incident_id=incident_id,
            type_limit=MAX_MEMORY_TYPES,
            candidate_limit=MAX_MEMORY_CANDIDATES,
        )
        memories = {}
        for row in rows:
            past = row["incident"]
            item = memories.setdefault(
                past["id"],
                {
                    "id": past["id"],
                    "timestamp": past["timestamp"],
                    "summary": past["summary"],
                    "shared_symptoms": sorted(set(row["shared_symptoms"])),
                    "confirmed_findings": [],
                },
            )
            if finding := row.get("finding"):
                if not any(f["id"] == finding["id"] for f in item["confirmed_findings"]):
                    item["confirmed_findings"].append(
                        {
                            **finding,
                            "causes": sorted(
                                (c for c in row["causes"] if c), key=lambda c: c["id"]
                            ),
                        }
                    )
        # Cypher already ranks by shared type count, recency and ID; preserve this order.
        return list(memories.values())

    def evidence_graph(self, entity_ids, incident_time=None):
        from knowledge.ontology import epoch_ms

        rows = self._read(
            EVIDENCE_GRAPH,
            entity_ids=sorted(set(entity_ids)),
            at=epoch_ms(incident_time) if incident_time else None,
        )
        edges = {
            (
                e["source"],
                e["type"],
                e["target"],
                json.dumps(e.get("properties", {}), sort_keys=True),
            ): e
            for r in rows
            for e in r["edges"]
            if e
        }
        return {"nodes": [r["node"] for r in rows], "edges": [edges[k] for k in sorted(edges)]}
