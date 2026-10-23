"""Fixed parameterized Cypher. Model output never becomes a database query."""

from config import DEMO_ID

LIST_INCIDENTS = """
MATCH (i:Incident {demo_id: $demo_id})-[:AFFECTS]->(c:Component {demo_id: $demo_id})
WHERE i.status = 'open'
RETURN i{.*, affected_component: c.id, affected_name: c.name} AS incident
ORDER BY i.id
"""

LOAD_INCIDENT = """
MATCH (i:Incident {id: $incident_id, demo_id: $demo_id})
      -[:AFFECTS]->(c:Component {demo_id: $demo_id})
RETURN i{.*, affected_component: c.id, affected_name: c.name} AS incident
"""

DEPENDENCIES = """
MATCH (i:Incident {id: $incident_id, demo_id: $demo_id})
      -[:AFFECTS]->(root:Component {demo_id: $demo_id})
MATCH p=(root)-[:DEPENDS_ON*0..3]->(upstream:Component)
WHERE all(n IN nodes(p) WHERE n.demo_id = $demo_id AND n:Component)
RETURN DISTINCT [n IN nodes(p) | n.id] AS path, upstream.id AS component_id
ORDER BY path
"""

RECENT_DEPLOYMENTS = """
MATCH (d:Deployment {demo_id: $demo_id})-[:CHANGED]->(c:Component {demo_id: $demo_id})
WHERE c.id IN $component_ids
  AND datetime(d.timestamp) <= datetime($incident_time)
  AND datetime(d.timestamp) >= datetime($incident_time) - duration({minutes: 30})
RETURN d.id AS deployment_id, d.timestamp AS deployed_at, d.description AS description,
       d.version AS version, c.id AS component_id
ORDER BY deployed_at DESC, deployment_id, component_id
"""

RECENT_SYMPTOMS = """
MATCH (s:Symptom {demo_id: $demo_id})-[:OBSERVED_ON]->(c:Component {demo_id: $demo_id})
WHERE c.id IN $component_ids
  AND datetime(s.timestamp) <= datetime($incident_time)
  AND datetime(s.timestamp) >= datetime($incident_time) - duration({minutes: 30})
RETURN s.id AS symptom_id, s.timestamp AS observed_at, s.type AS symptom_type,
       s.message AS message, c.id AS component_id
ORDER BY observed_at, symptom_id, component_id
"""

HISTORICAL_INCIDENTS = """
MATCH (current:Incident {id: $incident_id, demo_id: $demo_id})
      -[:HAS_SYMPTOM]->(s:Symptom {demo_id: $demo_id})
MATCH (past:Incident {demo_id: $demo_id})
      -[:HAS_SYMPTOM]->(old:Symptom {demo_id: $demo_id})
WHERE past.id <> current.id AND old.type = s.type
  AND datetime(past.timestamp) < datetime(current.timestamp)
WITH current, past, collect(DISTINCT s.type) AS shared_symptoms
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
MATCH (n {demo_id: $demo_id}) WHERE n.id IN $entity_ids
OPTIONAL MATCH (n)-[r:DEPENDS_ON|CHANGED|AFFECTS|HAS_SYMPTOM|OBSERVED_ON|EXPLAINS|ATTRIBUTED_TO]
               ->(m {demo_id: $demo_id})
WHERE m.id IN $entity_ids
RETURN n{.*, label: head(labels(n))} AS node,
       collect(DISTINCT CASE WHEN r IS NOT NULL
         THEN {source: n.id, target: m.id, type: type(r)} ELSE null END) AS edges
ORDER BY node.id
"""


class KnowledgeRepository:
    def __init__(self, database):
        self.database = database

    def _read(self, query, **params):
        return self.database.read(query, demo_id=DEMO_ID, **params)

    def list_incidents(self):
        return [r["incident"] for r in self._read(LIST_INCIDENTS)]

    def get_incident(self, incident_id):
        rows = self._read(LOAD_INCIDENT, incident_id=incident_id)
        return rows[0]["incident"] if rows else None

    def dependencies(self, incident_id):
        return self._read(DEPENDENCIES, incident_id=incident_id)

    def recent_deployments(self, component_ids, incident_time):
        return self._read(
            RECENT_DEPLOYMENTS, component_ids=component_ids, incident_time=incident_time
        )

    def symptoms(self, component_ids, incident_time):
        return self._read(RECENT_SYMPTOMS, component_ids=component_ids, incident_time=incident_time)

    def historical_incidents(self, incident_id):
        rows = self._read(HISTORICAL_INCIDENTS, incident_id=incident_id)
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

    def evidence_graph(self, entity_ids):
        rows = self._read(EVIDENCE_GRAPH, entity_ids=sorted(set(entity_ids)))
        edges = {(e["source"], e["type"], e["target"]): e for r in rows for e in r["edges"] if e}
        return {"nodes": [r["node"] for r in rows], "edges": [edges[k] for k in sorted(edges)]}
