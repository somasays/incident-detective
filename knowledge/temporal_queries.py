"""Bounded predefined temporal retrieval. User/model text never becomes Cypher."""

import re
from collections import deque
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from time import monotonic
from zoneinfo import ZoneInfo

from knowledge.temporal_fixture import DATA_AS_OF, DATASET, instant, iso
from knowledge.temporal_seed import spec

RUNTIME = ["System", "Component", "K8sWorkload", "K8sCluster", "StorageVolume"]
READ_DEADLINE = ContextVar("investigation_read_deadline", default=None)
MUTABLE = {
    "status",
    "revision",
    "version",
    "readyReplicas",
    "desiredReplicas",
    "availableReplicas",
    "imageDigest",
    "provisionedIops",
    "rolloutStatus",
    "clusterId",
    "kubernetesNamespace",
}


def available(var="n"):
    return (
        f"{var}.recordedAt <= $known AND "
        f"({var}.supersededAt IS NULL OR $known < {var}.supersededAt)"
    )


def effective(var="r"):
    return f"{var}.validFrom <= $at AND ({var}.validTo IS NULL OR $at < {var}.validTo)"


def jsonable(value):
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if hasattr(value, "iso_format"):
        return value.iso_format().replace("+00:00", "Z")
    if isinstance(value, datetime):
        return iso(value)
    return value


def normalize(value):
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def resolve_request(
    question,
    catalog,
    *,
    at=None,
    mode="retrospective",
    known_at=None,
    timezone="Europe/Berlin",
    reference_time=DATA_AS_OF,
):
    if not 3 <= len(question.strip()) <= 2000:
        raise ValueError("Enter a question between 3 and 2000 characters.")
    if mode not in {"retrospective", "known_then"}:
        raise ValueError("Unknown analysis mode")
    text = " " + normalize(question) + " "
    matches = []
    for entity in catalog:
        score = max(
            (
                len(normalize(alias).split())
                for alias in [entity.get("name", ""), *entity.get("aliases", [])]
                if alias and " " + normalize(alias) + " " in text
            ),
            default=0,
        )
        if score:
            matches.append((score, entity))
    if not matches:
        raise ValueError(
            "No known service/system in the question. Available: "
            + ", ".join(n["name"] for n in catalog)
        )
    best = max(score for score, _ in matches)
    candidates = [n for score, n in matches if score == best]
    if len(candidates) != 1:
        raise ValueError("Ambiguous service: " + ", ".join(n["name"] for n in candidates))
    local = instant(reference_time).astimezone(ZoneInfo(timezone))
    if at:
        parsed = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        selected = iso(parsed.astimezone(UTC))
    else:
        clock = re.search(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", question.lower())
        if clock:
            hour = int(clock[1])
            if not 1 <= hour <= 12:
                raise ValueError("Invalid AM/PM hour")
            hour = hour % 12 + (12 if clock[3] == "pm" else 0)
            if "yesterday" in question.lower():
                local -= timedelta(days=1)
            local = local.replace(hour=hour, minute=int(clock[2] or 0), second=0, microsecond=0)
            selected = iso(local.astimezone(UTC))
        else:
            if re.search(r"\b(at|yesterday|last night|last week|ago)\b", question.lower()):
                raise ValueError("Use --at (or the time control) for this time expression.")
            selected = reference_time
    known = known_at or (selected if mode == "known_then" else reference_time)
    if instant(selected) > instant(reference_time) or instant(known) > instant(reference_time):
        raise ValueError("Requested time exceeds the prepared dataset's coverage.")
    return {
        "question": question,
        "rootId": candidates[0]["id"],
        "rootLabel": candidates[0]["label"],
        "rootName": candidates[0]["name"],
        "effectiveAt": selected,
        "knowledgeAsOf": known,
        "mode": mode,
        "timezone": timezone,
        "dataAsOf": reference_time,
        "datasetId": DATASET,
        "synthetic": True,
    }


class TemporalRepository:
    def __init__(self, database):
        self.database = database
        self.ontology = spec()
        self.nodes = {n["label"]: n for n in self.ontology["nodes"].values()}
        self.trace = []
        self.notices = []
        self.property_keys = {
            r["propertyKey"]
            for r in self.database.read(
                "CYPHER 25 CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey LIMIT 1000"
            )
        }

    def read(self, name, query, **params):
        deadline = READ_DEADLINE.get()
        if deadline is not None and monotonic() + 25 > deadline:
            raise TimeoutError("Investigation deadline reached before starting another query")
        rows = jsonable(self.database.read("CYPHER 25 " + query, dataset=DATASET, **params))
        self.trace.append(
            {
                "tool": name,
                "parameters": jsonable(params),
                "rows": len(rows),
                "transport": getattr(self.database, "transport", "neo4j-driver/bolt"),
            }
        )
        return rows

    def projection(self, label, var="n"):
        # Explicit fields from the approved ontology, never arbitrary properties/model text.
        fields = [
            k
            for k in self.nodes[label]["properties"]
            if k in self.property_keys and k not in {"ingestedAt", "updatedAt"}
        ]
        if label in RUNTIME:
            fields = [k for k in fields if k not in MUTABLE]
        return var + "{" + ",".join("." + key for key in fields) + ",label:'" + label + "'}"

    def catalog(self):
        return [
            r["node"]
            for label in ["Component", "System"]
            for r in self.read(
                "catalog",
                f"MATCH (n:{label} {{datasetId:$dataset}}) RETURN "
                "n{.id,.name,.aliases,.environment,label:'" + label + "'} AS node "
                "ORDER BY n.id LIMIT 100",
            )
        ]

    def observe_target(self, request, entity_ids=None):
        """Initial symptoms only: no upstream telemetry or later postmortem is preloaded."""
        at, known = instant(request["effectiveAt"]), instant(request["knowledgeAsOf"])
        return self.read(
            "observe_target",
            f"MATCH (o:Observation {{datasetId:$dataset}})-[r:OBSERVED_ON]->"
            f"(c {{datasetId:$dataset}}) "
            f"WHERE c.id IN $ids AND {available('o')} AND {available('r')} "
            "AND o.timestamp >= $start AND o.timestamp <= $at "
            "RETURN o{.*,entityId:c.id,label:'Observation'} AS observation, "
            "r{.*,source:o.id,target:c.id,type:type(r)} AS edge "
            "ORDER BY o.timestamp,o.id LIMIT 40",
            ids=entity_ids or [request["rootId"]],
            known=known,
            at=at,
            start=at - timedelta(minutes=45),
        )

    def find_precedents(self, request, topology, signals):
        """Rank resolved, distinct older cases by actual shared patterns and topology overlap."""
        patterns = sorted(
            {
                o.get("errorType") or o.get("metricName")
                for row in signals
                for o in [row["observation"]]
                if o.get("errorType") or o.get("metricName")
            }
        )
        return self.read(
            "find_precedents",
            "MATCH (i:Incident {datasetId:$dataset})-[a:AFFECTS]->(c {datasetId:$dataset}) "
            "MATCH (i)-[ho:HAS_OBSERVATION]->(old:Observation {datasetId:$dataset}) "
            "MATCH (f:Finding {datasetId:$dataset,confirmed:true})-[ex:EXPLAINS]->(i) "
            "MATCH (f)-[att:ATTRIBUTED_TO]->(cause {datasetId:$dataset}) "
            "WHERE c.id IN $ids AND i.resolvedAt <= $before "
            "AND i.timestamp < $before AND f.confirmedAt <= $known "
            f"AND {available('i')} AND {available('f')} AND {available('old')} "
            f"AND {available('a')} AND {available('ho')} AND {available('ex')} "
            f"AND {available('att')} AND {available('cause')} "
            "AND old.timestamp <= i.resolvedAt "
            "WITH i,f,cause,ex,att,"
            "collect(DISTINCT coalesce(old.errorType,old.metricName)) AS patterns "
            "WITH i,f,cause,ex,att,patterns,[p IN patterns WHERE p IN $patterns] AS shared "
            "WHERE size(shared)>0 "
            "RETURN i{.id,.timestamp,.resolvedAt,.summary,label:'Incident'} AS incident, "
            "f{.id,.conclusion,.confirmedAt,label:'Finding'} AS finding, "
            "cause.id AS previousCauseId, shared AS sharedPatterns, "
            "cause{.id,.name,label:head(labels(cause))} AS cause, "
            "ex{.*,source:f.id,target:i.id,type:type(ex)} AS explains, "
            "att{.*,source:f.id,target:cause.id,type:type(att)} AS attribution "
            "ORDER BY size(shared) DESC,i.timestamp DESC,i.id LIMIT 3",
            ids=[n["id"] for n in topology["nodes"]],
            patterns=patterns,
            before=instant(request["effectiveAt"]) - timedelta(minutes=45),
            known=instant(request["knowledgeAsOf"]),
        )

    def neighbors(self, source_label, source, kinds, request):
        results = []
        for definition in self.ontology["relationships"].values():
            if definition["type"] not in kinds:
                continue
            left = self.ontology["nodes"][definition["from"]["node"]]["label"]
            right = self.ontology["nodes"][definition["to"]["node"]]["label"]
            if left != source_label:
                continue
            kind = definition["type"]
            rows = self.read(
                kind,
                f"MATCH (a:{left} {{id:$source,datasetId:$dataset}})-[r:{kind}]->"
                f"(n:{right} {{datasetId:$dataset}}) WHERE {available('r')} AND "
                f"{available()} AND {effective()} RETURN {self.projection(right)} AS node, "
                "r{.*,source:a.id,target:n.id,type:type(r)} AS edge ORDER BY n.id LIMIT 17",
                source=source,
                at=instant(request["effectiveAt"]),
                known=instant(request["knowledgeAsOf"]),
            )
            if len(rows) > 16:
                self.notices.append(f"{kind} neighborhood truncated at {source}")
            results.extend(rows[:16])
        return results

    def topology(self, request, max_depth=3):
        root = next(n for n in self.catalog() if n["id"] == request["rootId"])
        graph = {root["id"]: root}
        edges, paths = {}, {}
        roots = [root]
        if root["label"] == "System":
            rows = self.read(
                "system_components",
                "MATCH (n:Component {datasetId:$dataset})-[r:PART_OF]->"
                f"(s:System {{id:$root,datasetId:$dataset}}) WHERE {available('r')} AND "
                f"{available()} AND {effective()} RETURN {self.projection('Component')} AS node, "
                "r{.*,source:n.id,target:s.id,type:type(r)} AS edge ORDER BY n.id LIMIT 17",
                root=root["id"],
                at=instant(request["effectiveAt"]),
                known=instant(request["knowledgeAsOf"]),
            )
            roots = [r["node"] for r in rows[:16]]
            if len(rows) > 16:
                self.notices.append("System membership truncated at 16 components")
            for row in rows[:16]:
                graph[row["node"]["id"]] = row["node"]
                edges[row["edge"]["id"]] = row["edge"]
        queue = deque((n, 0, [n["id"]]) for n in roots)
        visited = set()
        while queue:
            node, depth, path = queue.popleft()
            if node["id"] in visited:
                continue
            visited.add(node["id"])
            paths[node["id"]] = path
            graph[node["id"]] = node
            if depth == max_depth:
                if max_depth == 3:
                    self.notices.append("Application traversal stops after three dependency hops")
                continue
            for row in self.neighbors(node["label"], node["id"], {"DEPENDS_ON"}, request):
                if len(graph) >= 32 and row["node"]["id"] not in graph:
                    self.notices.append("Application traversal reached 32 components")
                    continue
                graph[row["node"]["id"]] = row["node"]
                edges[row["edge"]["id"]] = row["edge"]
                queue.append((row["node"], depth + 1, path + [row["node"]["id"]]))
        for node in list(graph.values()):
            for row in self.neighbors(
                node["label"], node["id"], {"REALIZED_BY", "USES_STORAGE"}, request
            ):
                graph[row["node"]["id"]] = row["node"]
                edges[row["edge"]["id"]] = row["edge"]
                if row["node"]["label"] == "K8sWorkload":
                    for child in self.neighbors(
                        "K8sWorkload", row["node"]["id"], {"IN_CLUSTER", "USES_STORAGE"}, request
                    ):
                        graph[child["node"]["id"]] = child["node"]
                        edges[child["edge"]["id"]] = child["edge"]
        return {
            "nodes": list(graph.values()),
            "edges": list(edges.values()),
            "paths": list(paths.values()),
        }

    def collect(self, request, topology):
        at, known = instant(request["effectiveAt"]), instant(request["knowledgeAsOf"])
        ids = [n["id"] for n in topology["nodes"]]
        nodes = {n["id"]: n for n in topology["nodes"]}
        edges = {e["id"]: e for e in topology["edges"]}

        def remember(rows):
            for row in rows:
                if row.get("node"):
                    nodes[row["node"]["id"]] = row["node"]
                if row.get("edge"):
                    edges[row["edge"]["id"]] = row["edge"]

        observations = []
        states = []
        for label in RUNTIME:
            source_ids = [n["id"] for n in topology["nodes"] if n["label"] == label]
            if not source_ids:
                continue
            rows = self.read(
                "observations",
                f"MATCH (n:Observation {{datasetId:$dataset}})-[r:OBSERVED_ON]->"
                f"(c:{label} {{datasetId:$dataset}}) WHERE c.id IN $ids AND "
                f"{available()} AND {available('r')} "
                "AND n.timestamp >= $start AND n.timestamp <= $end "
                f"RETURN {self.projection('Observation')} AS node, "
                "r{.*,source:n.id,target:c.id,type:type(r)} AS edge, c.id AS entityId "
                "ORDER BY n.timestamp,n.id LIMIT 81",
                ids=source_ids,
                known=known,
                start=at - timedelta(minutes=45),
                end=at + timedelta(minutes=40),
            )
            if len(rows) > 80:
                self.notices.append(f"{label} observations capped at 80")
            rows = rows[:80]
            remember(rows)
            observations.extend([{**r["node"], "entityId": r["entityId"]} for r in rows])
            rows = self.read(
                "state_history",
                f"MATCH (c:{label} {{datasetId:$dataset}})-[r:HAS_STATE]->"
                f"(n:StateSnapshot {{datasetId:$dataset}}) WHERE c.id IN $ids AND "
                f"{available()} AND {available('r')} AND n.validFrom <= $end "
                "AND (n.validTo IS NULL OR n.validTo > $start) "
                f"RETURN {self.projection('StateSnapshot')} AS node, "
                "r{.*,source:c.id,target:n.id,type:type(r)} AS edge, c.id AS entityId "
                "ORDER BY n.validFrom,n.id LIMIT 41",
                ids=source_ids,
                known=known,
                start=at - timedelta(minutes=45),
                end=at + timedelta(minutes=40),
            )
            if len(rows) > 40:
                self.notices.append(f"{label} state history capped at 40")
            remember(rows[:40])
            states.extend([{**r["node"], "entityId": r["entityId"]} for r in rows[:40]])
        events = []
        for label, kind in [("Change", "APPLIED_TO"), ("Deployment", "CHANGED")]:
            for target in ["Component", "K8sWorkload", "K8sCluster", "StorageVolume"]:
                rows = self.read(
                    "recent_" + label.lower(),
                    f"MATCH (n:{label} {{datasetId:$dataset}})-[r:{kind}]->"
                    f"(c:{target} {{datasetId:$dataset}}) WHERE c.id IN $ids AND "
                    f"{available()} AND {available('r')} "
                    "AND n.timestamp >= $start AND n.timestamp <= $end "
                    f"RETURN {self.projection(label)} AS node, "
                    "r{.*,source:n.id,target:c.id,type:type(r)} AS edge, c.id AS entityId "
                    "ORDER BY n.timestamp,n.id LIMIT 21",
                    ids=ids,
                    known=known,
                    start=at - timedelta(minutes=60),
                    end=at + timedelta(minutes=40),
                )
                if len(rows) > 20:
                    self.notices.append("Recent change/deployment limit reached")
                remember(rows[:20])
                events.extend([{**r["node"], "entityId": r["entityId"]} for r in rows[:20]])
        # Running release is retrieved independently of the recent-change window.
        releases = []
        for resource in topology["nodes"]:
            rows = self.neighbors(resource["label"], resource["id"], {"RUNNING_RELEASE"}, request)
            remember(rows)
            releases.extend(r["node"] for r in rows)
        for release in {
            n["id"]: n for n in [*releases, *events] if n["label"] == "Deployment"
        }.values():
            for target in ["Commit", "CodeArtifact"]:
                rows = self.read(
                    "release_manifest",
                    "MATCH (d:Deployment {id:$release,datasetId:$dataset})-[r:INCLUDES]->"
                    f"(n:{target} {{datasetId:$dataset}}) WHERE {available()} AND {available('r')} "
                    f"RETURN {self.projection(target)} AS node, "
                    "r{.*,source:d.id,target:n.id,type:type(r)} AS edge ORDER BY n.id LIMIT 10",
                    release=release["id"],
                    known=known,
                )
                remember(rows)
        memories = []
        for target in RUNTIME:
            rows = self.read(
                "incident_history",
                "MATCH (i:Incident {datasetId:$dataset})-[r:AFFECTS]->"
                f"(c:{target} {{datasetId:$dataset}}) WHERE c.id IN $ids AND "
                f"{available('i')} AND {available('r')} AND i.timestamp <= $at "
                "RETURN i{.id,.summary,.timestamp,.sourceRef,.recordedAt,"
                "label:'Incident'} AS node, "
                "r{.*,source:i.id,target:c.id,type:type(r)} AS edge "
                "ORDER BY i.timestamp DESC LIMIT 5",
                ids=ids,
                known=known,
                at=at,
            )
            remember(rows)
            for row in rows:
                findings = self.read(
                    "confirmed_findings",
                    "MATCH (n:Finding {datasetId:$dataset,confirmed:true})-[r:EXPLAINS]->"
                    f"(i:Incident {{id:$incident,datasetId:$dataset}}) WHERE {available()} "
                    f"AND {available('r')} AND n.confirmedAt <= $known "
                    f"RETURN {self.projection('Finding')} AS node, "
                    "r{.*,source:n.id,target:i.id,type:type(r)} AS edge ORDER BY n.id LIMIT 5",
                    incident=row["node"]["id"],
                    known=known,
                )
                remember(findings)
                memories.extend({"incident": row["node"], "finding": f["node"]} for f in findings)
        # Include stored relationships; later supporting links remain knowledge filtered.
        for definition in self.ontology["relationships"].values():
            if definition["type"] not in {"ATTRIBUTED_TO", "SUPPORTED_BY", "AUTHORED", "COMMITTED"}:
                continue
            left = self.ontology["nodes"][definition["from"]["node"]]["label"]
            right = self.ontology["nodes"][definition["to"]["node"]]["label"]
            rows = self.read(
                "evidence_links",
                f"MATCH (a:{left} {{datasetId:$dataset}})-[r:{definition['type']}]->"
                f"(n:{right} {{datasetId:$dataset}}) WHERE n.id IN $ids AND "
                f"{available('a')} AND {available('r')} "
                f"RETURN {self.projection(left, 'a')} AS node, "
                "r{.*,source:a.id,target:n.id,type:type(r)} AS edge ORDER BY a.id LIMIT 10",
                ids=list(nodes),
                known=known,
            )
            remember(rows)
        measurements = []
        groups = {}
        for obs in observations:
            if obs["kind"] != "metric_window":
                continue
            stamp = instant(obs["windowEnd"])
            phase = (
                "baseline"
                if stamp <= at - timedelta(minutes=25)
                else (
                    "recovery"
                    if instant(obs["windowStart"]) >= at + timedelta(minutes=15)
                    else "incident"
                )
            )
            obs["phase"] = phase
            key = (
                obs["entityId"],
                obs["metricName"],
                obs["unit"],
                obs["aggregation"],
                tuple(obs.get("dimensions", [])),
            )
            groups.setdefault(key, {})[phase] = obs
        for key, phases in groups.items():
            row = {
                "entityId": key[0],
                "metric": key[1],
                "unit": key[2],
                "aggregation": key[3],
                "dimensions": list(key[4]),
                **{phase: o["value"] for phase, o in phases.items()},
                "evidenceIds": {phase: o["id"] for phase, o in phases.items()},
                "windows": {
                    phase: [o["windowStart"], o["windowEnd"]] for phase, o in phases.items()
                },
                "sampleCounts": {phase: o.get("sampleCount") for phase, o in phases.items()},
            }
            if "baseline" in phases and "incident" in phases:
                before, during = phases["baseline"]["value"], phases["incident"]["value"]
                row["difference"] = round(during - before, 4)
                row["ratio"] = round(during / before, 4) if before else None
                row["calculation"] = "incident - baseline; incident / baseline (if baseline != 0)"
            measurements.append(row)
        if len(nodes) > 150:
            raise ValueError("Evidence graph exceeds the 150-node investigation budget")
        return {
            "request": request,
            "baselinePolicy": {
                "kind": "prior_window_reference",
                "window": [iso(at - timedelta(minutes=45)), iso(at - timedelta(minutes=25))],
                "selection": "Match entity, metric, unit, aggregation and dimensions",
                "limitations": "Reference window; not a learned seasonal baseline or SLO",
            },
            "topology": topology,
            "measurements": measurements,
            "observations": observations,
            "states": states,
            "changes": events,
            "runningReleases": releases,
            "historicalFindings": memories,
            "graph": {"nodes": list(nodes.values()), "edges": list(edges.values())},
            "index": {**nodes, **edges},
            "queryTrace": self.trace,
            "limitations": [
                *sorted(set(self.notices)),
                "Prepared synthetic data; no live source systems or streaming pipeline.",
                "Only selected telemetry windows are available; missing data is not healthy state.",
                "Retrospective evidence can include recovery and later findings; times retained.",
            ],
        }
