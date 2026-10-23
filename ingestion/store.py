"""Commit a batch of facts and its source cursor in the SAME Neo4j transaction."""

from datetime import UTC, datetime

from ingestion.models import digest, entity_id
from knowledge.ontology import VERSION


class GraphWriter:
    def __init__(self, database, namespace):
        self.database, self.namespace = database, namespace

    def source_id(self, source):
        return entity_id(self.namespace, "IngestionSource", source.id)

    def state(self, source):
        rows = self.database.read(
            "MATCH (s:IngestionSource {id: $id, demo_id: $namespace}) RETURN s{.*} AS state",
            id=self.source_id(source),
            namespace=self.namespace,
        )
        return rows[0]["state"] if rows else {"offset": 0, "revision": 0}

    def commit(self, source, expected, mutations, checkpoint):
        namespace = self.namespace
        config_hash = digest(source.model_dump(mode="json"))
        source_id = self.source_id(source)

        def work(tx):
            # Lock before checking the revision so concurrent workers cannot skip data.
            state = tx.run(
                "MERGE (s:IngestionSource {id: $id}) "
                "ON CREATE SET s.demo_id=$namespace, s.offset=0, s.revision=0 "
                "SET s._ingestion_lock=true REMOVE s._ingestion_lock RETURN s{.*} AS state",
                id=source_id,
                namespace=namespace,
            ).single()["state"]
            if state["demo_id"] != namespace or state["revision"] != expected["revision"]:
                raise ValueError(
                    "Source cursor changed; retry this batch from its committed offset."
                )
            if state.get("config_hash", config_hash) != config_hash:
                raise ValueError("Source configuration changed. Use a new source ID.")
            if state.get("ontology_version", VERSION) != VERSION:
                raise ValueError(
                    "Source ontology version changed. An explicit migration is required."
                )
            catalog_at, catalog_hash = state.get("catalog_at"), state.get("catalog_hash")
            for mutation in mutations:
                if mutation.catalog_at is not None:
                    incoming_hash = digest(
                        [(n.id, n.properties["record_hash"]) for n in mutation.nodes]
                        + [(e.source, e.target) for e in mutation.edges]
                    )
                    if catalog_at is not None and mutation.catalog_at < catalog_at:
                        raise ValueError(
                            "Catalog snapshots must be chronological; cursor preserved."
                        )
                    if mutation.catalog_at == catalog_at:
                        if incoming_hash != catalog_hash:
                            raise ValueError("Conflicting catalog snapshots at the same timestamp.")
                        continue
                    tx.run(
                        "MATCH (:Component {demo_id:$namespace})-[r:DEPENDS_ON]->() "
                        "WHERE r.source_id=$source AND r.method='declared' "
                        "AND r.valid_to_ms IS NULL SET r.valid_to_ms=$at",
                        namespace=namespace,
                        source=source.id,
                        at=mutation.catalog_at,
                    ).consume()
                    catalog_at, catalog_hash = mutation.catalog_at, incoming_hash
                for node in mutation.nodes:
                    existing = tx.run(
                        f"MATCH (n:{node.label} {{id:$id}}) RETURN n{{.*}} AS node",
                        id=node.id,
                    ).single()
                    if existing:
                        old = existing["node"]
                        if old.get("demo_id") != namespace:
                            raise ValueError("Entity identity belongs to another namespace.")
                        if node.label != "Component":
                            if old.get("record_hash") != node.properties["record_hash"]:
                                raise ValueError(
                                    "Conflicting payload for immutable source event ID."
                                )
                            continue
                        old_priority = old.get("metadata_priority", 0)
                        priority = node.properties["metadata_priority"]
                        if priority < old_priority or (
                            priority == old_priority
                            and node.properties["metadata_timestamp_ms"]
                            < old.get("metadata_timestamp_ms", 0)
                        ):
                            tx.run(
                                "MATCH (n:Component {id:$id}) SET n.last_seen_ms = "
                                "CASE WHEN coalesce(n.last_seen_ms,0)<$seen THEN $seen "
                                "ELSE n.last_seen_ms END",
                                id=node.id,
                                seen=node.properties["last_seen_ms"],
                            ).consume()
                            continue
                    properties = node.properties
                    if existing and node.label == "Component":
                        properties = properties | {
                            "last_seen_ms": max(properties["last_seen_ms"], old["last_seen_ms"])
                        }
                    tx.run(
                        f"MERGE (n:{node.label} {{id:$id}}) SET n += $properties, "
                        "n.ingested_at=coalesce(n.ingested_at,$now)",
                        id=node.id,
                        properties=properties,
                        now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    ).consume()
                for edge in mutation.edges:
                    found = tx.run(
                        f"MATCH (a:{edge.source_label} {{id:$a,demo_id:$ns}}), "
                        f"(b:{edge.target_label} {{id:$b,demo_id:$ns}}) "
                        f"MERGE (a)-[r:{edge.kind} {{id:$id}}]->(b) "
                        "ON CREATE SET r += $properties "
                        "SET r.last_source_ref=$ref "
                        "RETURN r.valid_from_ms AS start, r.valid_to_ms AS end",
                        a=edge.source,
                        b=edge.target,
                        ns=namespace,
                        id=edge.properties["id"],
                        properties=edge.properties,
                        ref=edge.properties["source_ref"],
                    ).single()
                    if not found:
                        raise ValueError(
                            "Unresolved relationship endpoint. Import its source first; "
                            "this source cursor has not advanced."
                        )
                    if edge.properties.get("method") == "observed_trace":
                        tx.run(
                            "MATCH (:Component {id:$a,demo_id:$ns})"
                            "-[r:DEPENDS_ON {id:$id}]->(:Component {id:$b,demo_id:$ns}) "
                            "SET r.valid_from_ms=$start, r.valid_to_ms=$end",
                            a=edge.source,
                            b=edge.target,
                            ns=namespace,
                            id=edge.properties["id"],
                            start=min(found["start"], edge.properties["valid_from_ms"]),
                            end=max(found["end"], edge.properties["valid_to_ms"]),
                        ).consume()
            tx.run(
                "MATCH (s:IngestionSource {id:$id}) SET s += $checkpoint, "
                "s.revision=s.revision+1, s.config_hash=$hash, s.adapter=$adapter, "
                "s.source_id=$source, s.environment=$environment, s.path=$path, "
                "s.catalog_at=$catalog_at, s.catalog_hash=$catalog_hash, "
                "s.updated_at=$now, s.records=coalesce(s.records,0)+$records, "
                "s.ontology_version=$ontology_version",
                id=source_id,
                checkpoint=checkpoint,
                hash=config_hash,
                adapter=source.adapter,
                source=source.id,
                environment=source.environment,
                path=str(source.path),
                catalog_at=catalog_at,
                catalog_hash=catalog_hash,
                now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                records=len(mutations),
                ontology_version=VERSION,
            ).consume()

        self.database.write_transaction(work)
