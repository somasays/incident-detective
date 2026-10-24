"""Ontology-scoped, stable pages of stored graph records for the dashboard."""

from knowledge.temporal_fixture import DATASET
from knowledge.temporal_queries import jsonable
from knowledge.temporal_seed import spec


class GraphExplorer:
    def __init__(self, database):
        self.database = database
        self.labels = sorted(n["label"] for n in spec()["nodes"].values())

    def page(self, *, label="Component", search="", after="", edge_after="", limit=50):
        if label not in {"All types", *self.labels}:
            raise ValueError("Unknown ontology entity type")
        if not 1 <= limit <= 150 or len(search) > 200:
            raise ValueError("Invalid graph page or search size")
        labels = self.labels if label == "All types" else [label]
        predicate = (
            " AND any(k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS $search)"
            if search
            else ""
        )
        # Labels come exclusively from the approved ontology; all user values are parameters.
        branches = [
            f"MATCH (n:{kind} {{datasetId:$dataset}}) WHERE n.id > $after{predicate} "
            f"RETURN n{{.*,label:'{kind}'}} AS node ORDER BY n.id LIMIT $size"
            for kind in labels
        ]
        query = (
            branches[0]
            if len(branches) == 1
            else (
                "CALL () { "
                + " UNION ALL ".join(
                    "CALL () { " + branch + " } RETURN node" for branch in branches
                )
                + " } RETURN node ORDER BY node.id LIMIT $size"
            )
        )
        rows = jsonable(
            self.database.read(
                "CYPHER 25 " + query,
                dataset=DATASET,
                after=after,
                search=search.lower(),
                size=limit + 1,
            )
        )
        nodes = [row["node"] for row in rows[:limit]]
        ids = [n["id"] for n in nodes]
        edge_rows = []
        if ids:
            edge_branches = [
                f"MATCH (a:{kind} {{datasetId:$dataset}})-[r]->(b) "
                "WHERE a.id IN $ids AND b.id IN $ids AND b.datasetId=$dataset "
                "AND r.id > $edge_after "
                "RETURN r{.*,source:a.id,target:b.id,type:type(r)} AS edge "
                "ORDER BY r.id LIMIT 201"
                for kind in sorted({n["label"] for n in nodes})
            ]
            edge_query = (
                edge_branches[0]
                if len(edge_branches) == 1
                else (
                    "CALL () { "
                    + " UNION ALL ".join(
                        "CALL () { " + branch + " } RETURN edge" for branch in edge_branches
                    )
                    + " } RETURN edge ORDER BY edge.id LIMIT 201"
                )
            )
            edge_rows = jsonable(
                self.database.read(
                    "CYPHER 25 " + edge_query,
                    dataset=DATASET,
                    ids=ids,
                    edge_after=edge_after,
                )
            )
        return {
            "graph": {"nodes": nodes, "edges": [row["edge"] for row in edge_rows[:200]]},
            "next_cursor": nodes[-1]["id"] if len(rows) > limit else None,
            "next_edge_cursor": edge_rows[199]["edge"]["id"] if len(edge_rows) > 200 else None,
        }
