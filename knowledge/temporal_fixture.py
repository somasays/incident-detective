"""Prepared source-backed synthetic history. No scenario answers are passed to the agent."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

DATASET = "sre-temporal-v2"
PREFIX = DATASET + ":"
DATA_AS_OF = "2026-10-23T08:05:00Z"
FIXTURE = Path(__file__).parents[1] / "data" / "temporal_scenarios.json"
ONTOLOGY = Path(__file__).with_name("ontology.v2.json")


def instant(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def build_fixture():
    nodes, edges = [], []
    start = "2026-10-22T18:00:00Z"

    def node(label, key, recorded_at=start, **props):
        id = PREFIX + key
        nodes.append(
            {
                "label": label,
                "id": id,
                "datasetId": DATASET,
                "recordedAt": recorded_at,
                "sourceId": "prepared-local-exports",
                **props,
            }
        )
        return id

    def edge(kind, source, target, recorded_at=start, **props):
        id = PREFIX + "rel-" + str(len(edges) + 1).zfill(4)
        edges.append(
            {
                "id": id,
                "type": kind,
                "source": source,
                "target": target,
                "recordedAt": recorded_at,
                "sourceId": "prepared-local-exports",
                **props,
            }
        )
        return id

    def association(kind, source, target, valid_from=start, valid_to=None, recorded_at=None):
        props = {
            "validFrom": valid_from,
            "observedAt": valid_from,
            "timeBasis": "explicit_effective_time",
        }
        if valid_to:
            props["validTo"] = valid_to
        return edge(kind, source, target, recorded_at=recorded_at or valid_from, **props)

    resources = {}
    for name in ["payments", "identity", "billing", "profiles"]:
        resources[name] = node(
            "System",
            name,
            name=name.title(),
            environment="production",
            aliases=[name],
            observedAt=DATA_AS_OF,
        )
    definitions = [
        ("payments-api", "service", "payments", ["payment api", "payments api"]),
        ("auth-service", "service", "identity", ["auth", "authentication service"]),
        ("auth-db", "database", "identity", ["auth database"]),
        ("payments-db", "database", "payments", ["payments database"]),
        ("billing-api", "service", "billing", ["billing api", "billing system"]),
        ("billing-worker", "worker", "billing", []),
        ("ledger-adapter", "connector", "billing", []),
        ("profile-service", "service", "profiles", ["profile service", "profiles"]),
        ("profile-cache", "cache", "profiles", []),
        ("notification-worker", "worker", "billing", []),
    ]
    for name, kind, system, aliases in definitions:
        resources[name] = node(
            "Component",
            name,
            name=name,
            kind=kind,
            aliases=aliases,
            environment="production",
            observedAt=DATA_AS_OF,
        )
        association("PART_OF", resources[name], resources[system])
    for source, target in [
        ("payments-api", "auth-service"),
        ("auth-service", "auth-db"),
        ("payments-api", "payments-db"),
        ("billing-api", "billing-worker"),
        ("billing-worker", "ledger-adapter"),
        ("profile-service", "profile-cache"),
    ]:
        association("DEPENDS_ON", resources[source], resources[target])
    for name in ["cluster-east", "cluster-west"]:
        resources[name] = node(
            "K8sCluster",
            name,
            name=name,
            clusterId=name,
            environment="production",
            region="local-demo",
            observedAt=DATA_AS_OF,
        )
    for service in ["payments-api", "auth-service", "billing-worker", "profile-service"]:
        key = service + "-workload"
        resources[key] = node(
            "K8sWorkload",
            key,
            name=service,
            kind="Deployment",
            uid="synthetic-" + key,
            clusterId="cluster-east",
            kubernetesNamespace="commerce",
            observedAt=DATA_AS_OF,
        )
        association("REALIZED_BY", resources[service], resources[key])
        if service == "auth-service":
            # Preserve what was known before the later cluster migration, then its correction.
            migration, learned = "2026-10-23T01:50:00Z", "2026-10-23T01:50:05Z"
            edge(
                "IN_CLUSTER",
                resources[key],
                resources["cluster-east"],
                validFrom=start,
                recorded_at=start,
                supersededAt=learned,
            )
            association(
                "IN_CLUSTER",
                resources[key],
                resources["cluster-east"],
                valid_to=migration,
                recorded_at=learned,
            )
            association(
                "IN_CLUSTER",
                resources[key],
                resources["cluster-west"],
                valid_from=migration,
                recorded_at=learned,
            )
        else:
            association("IN_CLUSTER", resources[key], resources["cluster-east"])
    volume = resources["auth-volume"] = node(
        "StorageVolume",
        "auth-volume",
        name="auth-db-volume",
        backendId="vol-auth-001",
        environment="production",
        observedAt=DATA_AS_OF,
    )
    association("USES_STORAGE", resources["auth-db"], volume)

    def state(
        resource,
        key,
        valid_from,
        recorded_at=None,
        valid_to=None,
        superseded=None,
        facet="configuration",
        **values,
    ):
        props = {
            "stateKey": key.split("-revision")[0],
            "resourceKind": next(n["label"] for n in nodes if n["id"] == resources[resource]),
            "facet": facet,
            "validFrom": valid_from,
            "observedAt": valid_from,
            "timeBasis": "explicit_effective_time",
            **values,
        }
        if valid_to:
            props["validTo"] = valid_to
        if superseded:
            props["supersededAt"] = superseded
        id = node("StateSnapshot", key, recorded_at=recorded_at or valid_from, **props)
        edge("HAS_STATE", resources[resource], id, recorded_at=recorded_at or valid_from)
        return id

    low, low_known = "2026-10-23T00:40:00Z", "2026-10-23T00:40:05Z"
    restored, restore_known = "2026-10-23T01:20:00Z", "2026-10-23T01:20:05Z"
    state("auth-volume", "volume-before", start, superseded=low_known, provisionedIops=3000)
    state(
        "auth-volume",
        "volume-before-revision2",
        start,
        recorded_at=low_known,
        valid_to=low,
        provisionedIops=3000,
    )
    state(
        "auth-volume",
        "volume-low",
        low,
        recorded_at=low_known,
        superseded=restore_known,
        provisionedIops=300,
    )
    low_state = state(
        "auth-volume",
        "volume-low-revision2",
        low,
        recorded_at=restore_known,
        valid_to=restored,
        provisionedIops=300,
    )
    state(
        "auth-volume", "volume-restored", restored, recorded_at=restore_known, provisionedIops=3000
    )
    for resource in ["cluster-east", "cluster-west"]:
        state(resource, resource + "-status", start, facet="status", status="Ready")
    for service in ["payments-api", "auth-service", "billing-worker", "profile-service"]:
        state(
            service + "-workload",
            service + "-workload-config",
            start,
            desiredReplicas=4,
            kubernetesNamespace="commerce",
        )
        state(
            service + "-workload",
            service + "-workload-status",
            start,
            facet="status",
            readyReplicas=4,
            rolloutStatus="Complete",
        )
    state("profile-cache", "cache-before", start, valid_to="2026-10-23T07:35:00Z", maxClients=1000)
    state("profile-cache", "cache-after", "2026-10-23T07:35:00Z", maxClients=50)

    person = node(
        "Person",
        "operator",
        name="Alex Chen",
        identityProvider="synthetic-git",
        externalId="alex-demo",
    )
    manifests = [
        ("payments-r17", "payments-api", start, "17.0", "receipt_prefix = 'PAY'\n", "receipts.py"),
        (
            "payments-r18",
            "payments-api",
            "2026-10-23T00:50:00Z",
            "18.0",
            "receipt_prefix = 'PAYMENT'\n",
            "receipts.py",
        ),
        (
            "auth-r8",
            "auth-service",
            start,
            "8.0",
            "db_statement_timeout_ms = 2000\n",
            "settings.py",
        ),
        (
            "ledger-r4",
            "ledger-adapter",
            "2026-10-23T07:40:00Z",
            "4.0",
            "def account_id(value):\n    return str(value)\n",
            "mapping.py",
        ),
    ]
    for key, service, at, version, content, path in manifests:
        sha = hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()
        commit = node(
            "Commit",
            key + "-commit",
            recorded_at=at,
            repository="synthetic/" + service,
            sha=sha,
            timestamp=at,
            committedAt=at,
            message="Update " + path,
        )
        edge("AUTHORED", person, commit, recorded_at=at)
        edge("COMMITTED", person, commit, recorded_at=at)
        artifact = node(
            "CodeArtifact",
            key + "-code",
            recorded_at=at,
            repository="synthetic/" + service,
            revision=sha,
            path=path,
            language="python",
            content=content,
            lineStart=1,
            lineEnd=len(content.splitlines()),
            kind="file",
        )
        change = node(
            "Change",
            key + "-delta",
            recorded_at=at,
            kind="code",
            timestamp=at,
            description="Update " + path,
            afterValue=content,
        )
        edge("INTRODUCED", commit, change, recorded_at=at)
        edge("MODIFIES", change, artifact, recorded_at=at)
        deployment = node(
            "Deployment",
            key,
            recorded_at=at,
            timestamp=at,
            version=version,
            revision=sha,
            environment="production",
            description="Release " + version,
        )
        edge("INCLUDES", deployment, commit, recorded_at=at)
        edge("INCLUDES", deployment, artifact, recorded_at=at)
        edge("CHANGED", deployment, resources[service], recorded_at=at)
        end = "2026-10-23T00:50:00Z" if key == "payments-r17" else None
        association("RUNNING_RELEASE", resources[service], deployment, at, end)
        association("IMPLEMENTED_BY", resources[service], artifact, at, end)
    node(
        "Commit",
        "payments-unreleased",
        recorded_at="2026-10-23T00:45:00Z",
        repository="synthetic/payments-api",
        sha="f" * 40,
        timestamp="2026-10-23T00:45:00Z",
        message="Adjust HTTP connection handling",
    )
    for key, target, at, kind, before, after, description in [
        (
            "storage-17",
            "auth-volume",
            low,
            "storage_configuration",
            "3000",
            "300",
            "Update provisioned IOPS allocation",
        ),
        (
            "storage-18",
            "auth-volume",
            restored,
            "storage_configuration",
            "300",
            "3000",
            "Update provisioned IOPS allocation",
        ),
        (
            "db-patch-12",
            "auth-db",
            "2026-10-23T00:10:00Z",
            "database_patch",
            "15.7",
            "15.8",
            "Apply database maintenance patch",
        ),
        (
            "cache-config-9",
            "profile-cache",
            "2026-10-23T07:35:00Z",
            "configuration",
            "1000",
            "50",
            "Update maxclients setting",
        ),
    ]:
        change = node(
            "Change",
            key,
            recorded_at=at,
            timestamp=at,
            kind=kind,
            description=description,
            beforeValue=before,
            afterValue=after,
            status="applied",
        )
        edge("APPLIED_TO", change, resources[target], recorded_at=at)

    def observation(key, target, at, kind, **props):
        recorded = iso(instant(at) + timedelta(seconds=3))
        id = node(
            "Observation",
            key,
            recorded_at=recorded,
            timestamp=at,
            observedAt=at,
            kind=kind,
            **props,
        )
        edge("OBSERVED_ON", id, resources[target], recorded_at=recorded)
        return id

    series = [
        ("payments-api", "http.request.duration", "ms", "p95", [85, 1650, 92, 84, 88]),
        ("auth-service", "http.request.duration", "ms", "p95", [25, 1420, 28, 24, 26]),
        ("auth-db", "db.query.duration", "ms", "p95", [9, 1280, 11, 9, 10]),
        ("auth-db", "db.io_wait", "%", "mean", [2, 78, 3, 2, 2]),
        ("auth-db", "cpu.utilization", "%", "mean", [18, 22, 19, 18, 18]),
        ("auth-volume", "storage.read_latency", "ms", "p95", [1.2, 115, 1.5, 1.2, 1.3]),
        ("auth-volume", "storage.queue_depth", "requests", "mean", [2, 130, 3, 2, 2]),
        ("auth-volume", "storage.iops", "operations/s", "mean", [1800, 298, 1820, 1780, 1810]),
        ("payments-db", "db.query.duration", "ms", "p95", [8, 9, 8, 8, 8]),
        ("cluster-east", "cpu.utilization", "%", "mean", [38, 41, 39, 38, 38]),
        ("billing-api", "http.server.error_rate", "%", "ratio", [0.1, 0.1, 0.1, 0.1, 12.2]),
        ("profile-service", "http.request.duration", "ms", "p95", [60, 62, 60, 58, 950]),
    ]
    periods = ["00:20", "00:50", "01:25", "07:20", "07:55"]
    metric_ids = {}
    for index, (resource, metric, unit, aggregation, values) in enumerate(series):
        for period, value in zip(periods, values, strict=True):
            begin = "2026-10-23T" + period + ":00Z"
            end = iso(instant(begin) + timedelta(minutes=5))
            key = f"metric-{index}-{period.replace(':', '')}"
            metric_ids[(resource, period)] = observation(
                key,
                resource,
                end,
                "metric_window",
                metricName=metric,
                value=float(value),
                unit=unit,
                aggregation=aggregation,
                windowStart=begin,
                windowEnd=end,
                sampleCount=1200,
                dimensions=["environment=production", "scope=service"],
            )
    incident_observations = []
    for key, resource, at, error, count, message in [
        (
            "auth-db-wait",
            "auth-db",
            "00:56:00",
            "IO_WAIT",
            420,
            "query waiting on DataFileRead; elapsed_ms=1278",
        ),
        (
            "auth-timeout",
            "auth-service",
            "00:57:00",
            "DB_STATEMENT_TIMEOUT",
            180,
            "authentication lookup exceeded statement timeout",
        ),
        (
            "payments-timeout",
            "payments-api",
            "00:58:00",
            "UPSTREAM_TIMEOUT",
            96,
            "POST /payments: auth-service request timed out",
        ),
        (
            "billing-schema",
            "billing-worker",
            "07:56:00",
            "SCHEMA_MISMATCH",
            146,
            "account_id expected integer, received string from ledger-adapter",
        ),
        (
            "billing-500",
            "billing-api",
            "07:57:00",
            "HTTP_500",
            146,
            "POST /invoices: invoice validation failed",
        ),
        (
            "profile-cache-timeout",
            "profile-cache",
            "07:56:30",
            "MAX_CLIENTS_REACHED",
            210,
            "ERR max number of clients reached",
        ),
        (
            "profile-timeout",
            "profile-service",
            "07:58:00",
            "CACHE_TIMEOUT",
            83,
            "GET /profile: cache acquisition timed out",
        ),
        (
            "notification-noise",
            "notification-worker",
            "00:57:00",
            "DELIVERY_RETRY",
            4,
            "notification delivery scheduled for retry",
        ),
    ]:
        at = "2026-10-23T" + at + "Z"
        id = observation(
            key,
            resource,
            at,
            "error_event",
            errorType=error,
            type=error,
            eventCount=count,
            message=message,
            severity="ERROR",
            windowStart=iso(instant(at) - timedelta(minutes=5)),
            windowEnd=at,
            fingerprint=error.lower(),
        )
        if resource in {"payments-api", "auth-service", "auth-db"}:
            incident_observations.append(id)
    observation(
        "payments-latency-alert",
        "payments-api",
        "2026-10-23T00:56:00Z",
        "alert",
        alertRule="payments_p95_above_500ms",
        threshold=500.0,
        thresholdUnit="ms",
        value=1650.0,
        unit="ms",
        severity="critical",
        message="Payments p95 latency exceeded 500 ms for five minutes",
    )
    # Timings are source samples, not inferred from topology. Nested waits are not summed.
    for key, resource, metric, duration in [
        ("trace-payments", "payments-api", "POST /payments", 1680),
        ("trace-auth", "auth-service", "POST /authorize", 1450),
        ("trace-db", "auth-db", "SELECT account", 1310),
    ]:
        observation(
            key,
            resource,
            "2026-10-23T00:58:30Z",
            "trace_summary",
            traceId="a1" * 16,
            spanId=hashlib.sha1(key.encode()).hexdigest()[:16],
            message=metric,
            metricName="span.duration",
            value=float(duration),
            unit="ms",
        )
    # A later-arriving observation is available to retrospective analysis, not known-then replay.
    late = observation(
        "late-storage-alert",
        "auth-volume",
        "2026-10-23T00:54:00Z",
        "alert",
        alertRule="volume_queue_above_100",
        threshold=100.0,
        thresholdUnit="requests",
        value=130.0,
        unit="requests",
        message="Storage queue depth exceeded evaluation threshold",
    )
    next(n for n in nodes if n["id"] == late)["recordedAt"] = "2026-10-23T02:00:00Z"
    next(e for e in edges if e["source"] == late)["recordedAt"] = "2026-10-23T02:00:00Z"
    incident = node(
        "Incident",
        "INC-201",
        recorded_at="2026-10-23T00:56:00Z",
        timestamp="2026-10-23T00:55:00Z",
        summary="Payments request latency elevated",
        severity="SEV-2",
        status="resolved",
        resolvedAt="2026-10-23T01:30:00Z",
    )
    edge("AFFECTS", incident, resources["payments-api"], recorded_at="2026-10-23T00:56:00Z")
    for id in incident_observations:
        edge("HAS_OBSERVATION", incident, id, recorded_at="2026-10-23T00:59:00Z")
    finding = node(
        "Finding",
        "finding-201",
        recorded_at="2026-10-23T04:00:00Z",
        createdAt="2026-10-23T04:00:00Z",
        confirmedAt="2026-10-23T04:00:00Z",
        confirmed=True,
        confirmedBy="Synthetic postmortem reviewer",
        conclusion="A provisioned IOPS reduction increased Auth DB I/O waits. "
        "Restoring allocation was followed by latency recovery; the review "
        "verified the storage configuration change as the incident trigger.",
    )
    edge("EXPLAINS", finding, incident, recorded_at="2026-10-23T04:00:00Z")
    edge("ATTRIBUTED_TO", finding, PREFIX + "storage-17", recorded_at="2026-10-23T04:00:00Z")
    edge("SUPPORTED_BY", finding, low_state, recorded_at="2026-10-23T04:00:00Z")
    edge(
        "SUPPORTED_BY",
        finding,
        metric_ids[("auth-volume", "00:50")],
        recorded_at="2026-10-23T04:00:00Z",
    )
    # Closing an interval is new knowledge. Retain the previously open assertion as well.
    for record in list(nodes):
        if (
            record["label"] == "StateSnapshot"
            and record.get("validTo")
            and (instant(record["recordedAt"]) < instant(record["validTo"]))
        ):
            learned = iso(instant(record["validTo"]) + timedelta(seconds=5))
            old = {**record, "id": record["id"] + "-initial", "supersededAt": learned}
            old.pop("validTo")
            nodes.append(old)
            owner = next(
                e["source"]
                for e in edges
                if e["type"] == "HAS_STATE" and e["target"] == record["id"]
            )
            edge("HAS_STATE", owner, old["id"], recorded_at=record["recordedAt"])
            record["recordedAt"] = learned
    for record in list(edges):
        if record.get("validTo") and instant(record["recordedAt"]) < instant(record["validTo"]):
            learned = iso(instant(record["validTo"]) + timedelta(seconds=5))
            old = {**record, "id": record["id"] + "-initial", "supersededAt": learned}
            old.pop("validTo")
            edges.append(old)
            record["recordedAt"] = learned
    # Resolved precedents are distinct from INC-201. Append to preserve existing source IDs/hashes.
    prior_cases = [
        ("INC-184", "2026-10-22T19:00:00Z", "payments-api", "auth-volume",
         "Storage maintenance saturated the Auth DB volume queue; pausing maintenance restored "
         "authentication and payments latency.",
         [("payments-api", "UPSTREAM_TIMEOUT"), ("auth-db", "IO_WAIT")]),
        ("INC-187", "2026-10-22T21:00:00Z", "payments-api", "auth-db",
         "A database patch changed an authentication query plan; restoring the earlier plan "
         "reduced query latency and payments timeouts.",
         [("payments-api", "UPSTREAM_TIMEOUT"), ("auth-service", "DB_STATEMENT_TIMEOUT")]),
        ("INC-188", "2026-10-22T20:00:00Z", "billing-api", "ledger-adapter",
         "An adapter release changed a numeric field to a string, causing schema failures "
         "in the billing worker.",
         [("billing-api", "HTTP_500"), ("billing-worker", "SCHEMA_MISMATCH")]),
        ("INC-189", "2026-10-22T20:15:00Z", "profile-service", "profile-cache",
         "A cache client limit was lowered; rejected connections caused profile timeouts. "
         "Restoring the connection limit resolved the incident.",
         [("profile-service", "CACHE_TIMEOUT"), ("profile-cache", "MAX_CLIENTS_REACHED")]),
    ]
    for key, when, affected, cause, conclusion, signals in prior_cases:
        resolved = iso(instant(when) + timedelta(minutes=20))
        confirmed = iso(instant(when) + timedelta(minutes=30))
        past = node("Incident", key, recorded_at=when, timestamp=when, resolvedAt=resolved,
                    status="resolved", severity="SEV-2", summary=f"Earlier {affected} degradation")
        edge("AFFECTS", past, resources[affected], recorded_at=when)
        observations = []
        for index, (entity, error_type) in enumerate(signals):
            signal = observation(f"{key}-signal-{index}", entity, when, "log_pattern",
                                 errorType=error_type, eventCount=40,
                                 message=f"Historical {error_type} on {entity}")
            edge("HAS_OBSERVATION", past, signal, recorded_at=when)
            observations.append(signal)
        prior_finding = node("Finding", f"finding-{key}", recorded_at=confirmed,
            createdAt=confirmed, confirmedAt=confirmed, confirmed=True,
            confirmedBy="Synthetic postmortem reviewer", conclusion=conclusion)
        edge("EXPLAINS", prior_finding, past, recorded_at=confirmed)
        edge("ATTRIBUTED_TO", prior_finding, resources[cause], recorded_at=confirmed)
        for signal in observations:
            edge("SUPPORTED_BY", prior_finding, signal, recorded_at=confirmed)
    # Fixture provenance is resolvable; no fictitious production endpoint is required.
    for kind, records in [("nodes", nodes), ("relationships", edges)]:
        for index, record in enumerate(records):
            record["sourceRef"] = f"data/temporal_scenarios.json#/{kind}/{index}"
            record["recordHash"] = hashlib.sha256(
                json.dumps(record, sort_keys=True).encode()
            ).hexdigest()
    return {
        "datasetId": DATASET,
        "ontologyVersion": "2.0.0",
        "synthetic": True,
        "dataAsOf": DATA_AS_OF,
        "timezone": "Europe/Berlin",
        "nodes": nodes,
        "relationships": edges,
    }


if __name__ == "__main__":
    fixture = build_fixture()
    FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n")
    print(f"Prepared {len(fixture['nodes'])} nodes / {len(fixture['relationships'])} relationships")
