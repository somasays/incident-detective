"""Typed diagnostic tools backed by fixed, temporal, read-only Neo4j queries."""

from collections import deque
from copy import deepcopy
from datetime import timedelta
from time import monotonic

from knowledge.temporal_fixture import instant
from knowledge.temporal_queries import RUNTIME, available, effective

TOOL_DESCRIPTIONS = {
    "expand_dependencies": "Discover ONE hop from exactly the selected resource IDs. "
    "New neighbors can themselves be expanded in a later check; their data is not preloaded.",
    "inspect_observations": "Read metric windows, errors, alerts and traces ONLY for the selected "
    "resource IDs. Does not inspect their dependencies, infrastructure or neighboring resources.",
    "inspect_state_changes": "Read configuration history and changes ONLY on the selected resource "
    "IDs. A service query does not inspect its database; "
    "a database query does not inspect storage.",
    "inspect_running_code": "Read code/commits in the running release of exactly the selected "
    "resources, not code running on their dependencies.",
}


def owned_evidence_ids(package, resource_id):
    reached = {resource_id}
    for _ in range(3):
        reached |= {
            e["target"] if e["source"] in reached else e["source"]
            for e in package["graph"]["edges"]
            if e["type"]
            in {
                "HAS_STATE",
                "APPLIED_TO",
                "CHANGED",
                "RUNNING_RELEASE",
                "INCLUDES",
                "REALIZED_BY",
                "OBSERVED_ON",
            }
            and (e["source"] in reached or e["target"] in reached)
        }
    return reached


class BudgetExhausted(RuntimeError):
    pass


def empty_package(request):
    return {
        "request": request,
        "topology": {"nodes": [], "edges": [], "paths": []},
        "graph": {"nodes": [], "edges": []},
        "index": {},
        "observations": [],
        "states": [],
        "changes": [],
        "runningReleases": [],
        "historicalFindings": [],
        "measurements": [],
        "queryTrace": [],
        "limitations": [
            "Prepared synthetic evidence; no live source systems are connected.",
            "Prior-window measurements are references, not learned baselines or SLOs.",
            "Missing telemetry is not evidence that a resource was healthy.",
        ],
    }


def merge_evidence(package, addition):
    result = deepcopy(package)
    for key in ["observations", "states", "changes", "runningReleases"]:
        records = {r["id"]: r for r in result.get(key, [])}
        records.update({r["id"]: r for r in addition.get(key, [])})
        result[key] = list(records.values())
    for kind in ["nodes", "edges"]:
        records = {r["id"]: r for r in result["graph"][kind]}
        records.update({r["id"]: r for r in addition.get("graph", {}).get(kind, [])})
        result["graph"][kind] = list(records.values())
    if len(result["graph"]["nodes"]) > 150 or len(result["graph"]["edges"]) > 300:
        raise BudgetExhausted("Investigation graph reached its 150-node/300-edge budget")
    result["index"] = {r["id"]: r for r in [*result["graph"]["nodes"], *result["graph"]["edges"]]}
    result["limitations"] = sorted(set([*result["limitations"], *addition.get("limitations", [])]))
    result["measurements"] = measurement_rows(result["observations"], result["request"])
    return result


def measurement_rows(observations, request):
    at = instant(request["effectiveAt"])
    groups = {}
    for observation in observations:
        if observation.get("kind") != "metric_window":
            continue
        phase = (
            "baseline"
            if instant(observation["windowEnd"]) <= at - timedelta(minutes=25)
            else "recovery"
            if instant(observation["windowStart"]) >= at + timedelta(minutes=15)
            else "incident"
        )
        key = (
            observation["entityId"],
            observation["metricName"],
            observation["unit"],
            observation["aggregation"],
            tuple(sorted(observation.get("dimensions", []))),
        )
        current = groups.setdefault(key, {}).get(phase)
        if current is None or (observation["windowEnd"], observation["id"]) > (
            current["windowEnd"],
            current["id"],
        ):
            groups[key][phase] = observation
    rows = []
    for key, phases in sorted(groups.items()):
        row = {
            "entityId": key[0],
            "metric": key[1],
            "unit": key[2],
            "aggregation": key[3],
            "dimensions": list(key[4]),
            **{p: o["value"] for p, o in phases.items()},
            "evidenceIds": {p: o["id"] for p, o in phases.items()},
            "windows": {p: [o["windowStart"], o["windowEnd"]] for p, o in phases.items()},
            "sampleCounts": {p: o.get("sampleCount") for p, o in phases.items()},
        }
        if "baseline" in phases and "incident" in phases:
            before, during = row["baseline"], row["incident"]
            row.update(
                difference=round(during - before, 4),
                ratio=round(during / before, 4) if before else None,
                calculation="incident - baseline; incident / baseline (if baseline != 0)",
            )
        rows.append(row)
    return rows


def runtime_depths(topology, request):
    adjacency = {}
    roots = {request["rootId"]}
    for edge in topology["edges"]:
        if edge["type"] == "PART_OF" and edge["target"] == request["rootId"]:
            roots.add(edge["source"])
        if edge["type"] in {"DEPENDS_ON", "REALIZED_BY", "USES_STORAGE", "IN_CLUSTER"}:
            adjacency.setdefault(edge["source"], []).append(edge)
    depths = {root: 0 for root in roots}
    queue = deque(roots)
    while queue:
        source = queue.popleft()
        for edge in adjacency.get(source, []):
            depth = depths[source] + (edge["type"] == "DEPENDS_ON")
            if edge["target"] not in depths or depth < depths[edge["target"]]:
                depths[edge["target"]] = depth
                queue.append(edge["target"])
    return depths


class DiagnosticTools:
    def __init__(self, repository):
        self.repository = repository

    def read(self, name, query, deadline, **params):
        # MCP calls have a 25-second upper bound; never start one outside the remaining budget.
        if monotonic() + 25 > deadline:
            raise BudgetExhausted("Investigation deadline reached")
        return self.repository.read(name, query, **params)

    def execute(self, tool, entity_ids, package, deadline, max_hops=3):
        if tool not in TOOL_DESCRIPTIONS:
            raise ValueError("Unknown diagnostic tool")
        known = {n["id"]: n for n in package["topology"]["nodes"]}
        if not 1 <= len(entity_ids) <= 3 or not set(entity_ids) <= known.keys():
            raise ValueError("Tools accept one to three currently connected resource IDs")
        if any(known[e]["label"] not in RUNTIME for e in entity_ids):
            raise ValueError("Only runtime resource identities may be inspected")
        request = package["request"]
        at, known_at = instant(request["effectiveAt"]), instant(request["knowledgeAsOf"])
        result = empty_package(request)
        result["limitations"] = []
        query_start = len(self.repository.trace)

        def remember(rows, category=None):
            for row in rows:
                if row.get("node"):
                    result["graph"]["nodes"].append(row["node"])
                    if category:
                        result[category].append(
                            {
                                **row["node"],
                                **({"entityId": row["entityId"]} if row.get("entityId") else {}),
                            }
                        )
                if row.get("edge"):
                    result["graph"]["edges"].append(row["edge"])

        params = {
            "ids": entity_ids,
            "known": known_at,
            "at": at,
            "start": at - timedelta(minutes=45),
            "end": at + timedelta(minutes=40),
        }
        projection = self.repository.projection
        try:
            if tool == "expand_dependencies":
                depths = runtime_depths(package["topology"], request)
                for source in entity_ids:
                    kinds = {"REALIZED_BY", "USES_STORAGE", "IN_CLUSTER"}
                    if depths.get(source, max_hops) < max_hops:
                        kinds.add("DEPENDS_ON")
                    else:
                        result["limitations"].append(f"Dependency depth capped at {max_hops} hops")
                    for definition in self.repository.ontology["relationships"].values():
                        if definition["type"] not in kinds:
                            continue
                        left = self.repository.ontology["nodes"][definition["from"]["node"]][
                            "label"
                        ]
                        right = self.repository.ontology["nodes"][definition["to"]["node"]]["label"]
                        if left != known[source]["label"]:
                            continue
                        rows = self.read(
                            tool,
                            f"MATCH (a:{left} {{id:$source,datasetId:$dataset}})"
                            f"-[r:{definition['type']}]->(n:{right} {{datasetId:$dataset}}) "
                            f"WHERE {available()} AND {available('r')} AND {effective()} "
                            f"RETURN {projection(right)} AS node, "
                            "r{.*,source:a.id,target:n.id,type:type(r)} AS edge "
                            "ORDER BY n.id LIMIT 17",
                            deadline,
                            source=source,
                            known=known_at,
                            at=at,
                        )
                        remember(rows[:16])
                        if len(rows) > 16:
                            result["limitations"].append("Dependency neighborhood capped at 16")
            elif tool == "inspect_observations":
                rows = self.read(
                    tool,
                    "MATCH (n:Observation {datasetId:$dataset})-[r:OBSERVED_ON]->"
                    "(c {datasetId:$dataset}) WHERE c.id IN $ids "
                    f"AND {available()} AND {available('r')} "
                    "AND n.timestamp >= $start AND n.timestamp <= $end "
                    f"RETURN {projection('Observation')} AS node, "
                    "r{.*,source:n.id,target:c.id,type:type(r)} AS edge, c.id AS entityId "
                    "ORDER BY n.timestamp,n.id LIMIT 81",
                    deadline,
                    **params,
                )
                remember(rows[:80], "observations")
                if len(rows) > 80:
                    result["limitations"].append("Observation result capped at 80")
            elif tool == "inspect_state_changes":
                rows = self.read(
                    tool,
                    "MATCH (c {datasetId:$dataset})-[r:HAS_STATE]->"
                    "(n:StateSnapshot {datasetId:$dataset}) WHERE c.id IN $ids "
                    f"AND {available()} AND {available('r')} AND n.validFrom <= $end "
                    "AND (n.validTo IS NULL OR n.validTo > $start) "
                    f"RETURN {projection('StateSnapshot')} AS node, "
                    "r{.*,source:c.id,target:n.id,type:type(r)} AS edge,c.id AS entityId "
                    "ORDER BY n.validFrom,n.id LIMIT 41",
                    deadline,
                    **params,
                )
                remember(rows[:40], "states")
                if len(rows) > 40:
                    result["limitations"].append("State result capped at 40")
                for label, kind in [("Change", "APPLIED_TO"), ("Deployment", "CHANGED")]:
                    rows = self.read(
                        tool,
                        f"MATCH (n:{label} {{datasetId:$dataset}})-[r:{kind}]->"
                        "(c {datasetId:$dataset}) WHERE c.id IN $ids "
                        f"AND {available()} AND {available('r')} "
                        "AND n.timestamp >= $start AND n.timestamp <= $end "
                        f"RETURN {projection(label)} AS node, "
                        "r{.*,source:n.id,target:c.id,type:type(r)} AS edge,c.id AS entityId "
                        "ORDER BY n.timestamp,n.id LIMIT 21",
                        deadline,
                        **{**params, "start": at - timedelta(minutes=60)},
                    )
                    remember(rows[:20], "changes")
                    if len(rows) > 20:
                        result["limitations"].append("Change result capped at 20")
            elif tool == "inspect_running_code":
                rows = self.read(
                    tool,
                    "MATCH (c {datasetId:$dataset})-[r:RUNNING_RELEASE]->"
                    "(n:Deployment {datasetId:$dataset}) WHERE c.id IN $ids "
                    f"AND {available()} AND {available('r')} AND {effective()} "
                    f"RETURN {projection('Deployment')} AS node, "
                    "r{.*,source:c.id,target:n.id,type:type(r)} AS edge,c.id AS entityId "
                    "ORDER BY n.id LIMIT 10",
                    deadline,
                    **params,
                )
                remember(rows, "runningReleases")
                for release in result["runningReleases"]:
                    for label in ["Commit", "CodeArtifact"]:
                        rows = self.read(
                            tool,
                            "MATCH (d:Deployment {id:$release,datasetId:$dataset})-[r:INCLUDES]->"
                            f"(n:{label} {{datasetId:$dataset}}) "
                            f"WHERE {available()} AND {available('r')} "
                            f"RETURN {projection(label)} AS node, "
                            "r{.*,source:d.id,target:n.id,type:type(r)} AS edge "
                            "ORDER BY n.id LIMIT 10",
                            deadline,
                            release=release["id"],
                            known=known_at,
                        )
                        remember(rows)
        except (BudgetExhausted, TimeoutError) as exc:
            # Preserve records returned by earlier queries within the same tool call.
            result["stopReason"] = str(exc)
        except Exception as exc:
            result["error"] = (
                f"Diagnostic tool failed ({type(exc).__name__}); partial evidence retained"
            )
        result["queries"] = deepcopy(self.repository.trace[query_start:])
        result["evidenceIds"] = [n["id"] for n in result["graph"]["nodes"]]
        result["coverage"] = {
            "queriedEntityIds": entity_ids,
            "scope": TOOL_DESCRIPTIONS[tool],
            "returnedResourceIds": [
                n["id"] for n in result["graph"]["nodes"] if n["label"] in RUNTIME
            ],
        }
        return result
