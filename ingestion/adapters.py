"""Source facts → ontology mutations. No hand-authored edges and no model-generated facts."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, field_validator

from ingestion.models import Edge, Mutation, Node, Source, StrictModel, digest, entity_id
from knowledge.ontology import VERSION, epoch_ms, utc


class Service(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    type: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=1000)
    depends_on: list[str] = Field(default_factory=list, max_length=100)


class Catalog(StrictModel):
    observed_at: str
    services: list[Service] = Field(max_length=1000)


class Event(StrictModel):
    id: str = Field(min_length=1, max_length=160)
    service: str = Field(min_length=1, max_length=160)
    timestamp: str

    @field_validator("timestamp")
    @classmethod
    def timestamp_is_utc(cls, value):
        return utc(value)


class Deployment(Event):
    version: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)


class Log(Event):
    severity: Literal["DEBUG", "INFO", "WARN", "ERROR", "FATAL"]
    error_type: str | None = Field(default=None, min_length=1, max_length=160)
    message: str = Field(min_length=1, max_length=4000)
    incident_id: str | None = Field(default=None, min_length=1, max_length=160)
    # The incident source owning incident_id must be explicit; log source IDs are independent.
    incident_source: str | None = Field(default=None, min_length=1, max_length=80)


class Incident(Event):
    summary: str = Field(min_length=1, max_length=2000)
    severity: str = Field(min_length=1, max_length=80)
    status: Literal["open", "closed"] = "open"


class Adapter:
    def __init__(self, namespace: str, source: Source):
        self.namespace, self.source = namespace, source

    def component_id(self, service):
        return entity_id(self.namespace, "Component", self.source.environment, service)

    def event_id(self, label, id, source=None):
        return entity_id(self.namespace, label, source or self.source.id, id)

    def convert(self, record: dict, line: int) -> Mutation:
        self.meta = {
            "demo_id": self.namespace,
            "source_id": self.source.id,
            "source_ref": f"{self.source.path}:{line}",
            "record_hash": digest(record),
            "environment": self.source.environment,
            "ontology_version": VERSION,
        }
        self.result = Mutation()
        getattr(self, self.source.adapter)(record)
        return self.result

    def component(self, service, timestamp, definition=None):
        id = self.component_id(service)
        self.result.nodes.append(
            Node(
                "Component",
                id,
                self.meta
                | {
                    "name": service,
                    "type": definition.type if definition else "service",
                    "description": definition.description
                    if definition
                    else "Observed in source data.",
                    "metadata_priority": 10 if definition else 1,
                    "metadata_timestamp_ms": epoch_ms(timestamp),
                    "last_seen_ms": epoch_ms(timestamp),
                },
            )
        )
        return id

    def edge(self, kind, source, target, source_label, target_label, **properties):
        identity = [kind, source, target, self.source.id, properties.pop("identity", "")]
        self.result.edges.append(
            Edge(
                kind,
                source,
                target,
                source_label,
                target_label,
                self.meta | {"id": digest(identity), **properties},
            )
        )

    def event(self, label, event, properties):
        id = self.event_id(label, event.id)
        component = self.component(event.service, event.timestamp)
        self.result.nodes.append(
            Node(
                label,
                id,
                self.meta
                | {
                    "timestamp": event.timestamp,
                    "timestamp_ms": epoch_ms(event.timestamp),
                    "external_id": event.id,
                    "component_id": component,
                    **properties,
                },
            )
        )
        return id, component

    def catalog(self, record):
        snapshot = Catalog.model_validate(record)
        timestamp = utc(snapshot.observed_at)
        self.result.catalog_at = epoch_ms(timestamp)
        names = {s.name for s in snapshot.services}
        if len(names) != len(snapshot.services):
            raise ValueError("Duplicate service identities in catalog snapshot.")
        for service in snapshot.services:
            if not set(service.depends_on) <= names:
                raise ValueError("Catalog dependency target must be defined in this snapshot.")
            if service.name in service.depends_on:
                raise ValueError("A service cannot depend on itself.")
            self.component(service.name, timestamp, service)
            for dependency in sorted(set(service.depends_on)):
                self.edge(
                    "DEPENDS_ON",
                    self.component_id(service.name),
                    self.component_id(dependency),
                    "Component",
                    "Component",
                    method="declared",
                    observed_at=timestamp,
                    valid_from_ms=epoch_ms(timestamp),
                    identity=timestamp,
                )

    def deployments(self, record):
        event = Deployment.model_validate(record)
        id, component = self.event(
            "Deployment",
            event,
            {
                "version": event.version,
                "description": event.description,
            },
        )
        self.edge("CHANGED", id, component, "Deployment", "Component", method="deployment_record")

    def incidents(self, record):
        event = Incident.model_validate(record)
        id, component = self.event(
            "Incident",
            event,
            {
                "summary": event.summary,
                "severity": event.severity,
                "status": event.status,
            },
        )
        self.edge("AFFECTS", id, component, "Incident", "Component", method="incident_record")

    def logs(self, record):
        event = Log.model_validate(record)
        if event.severity in {"DEBUG", "INFO"} or not event.error_type:
            return
        if bool(event.incident_id) != bool(event.incident_source):
            raise ValueError("An incident link requires both incident_id and incident_source.")
        id, component = self.event(
            "Symptom",
            event,
            {
                "type": event.error_type,
                "message": event.message,
            },
        )
        self.edge("OBSERVED_ON", id, component, "Symptom", "Component", method="structured_log")
        if event.incident_id:
            self.edge(
                "HAS_SYMPTOM",
                self.event_id("Incident", event.incident_id, event.incident_source),
                id,
                "Incident",
                "Symptom",
                method="explicit_incident_reference",
            )

    def otlp(self, record):
        # Supported OTLP/JSON ExportTraceServiceRequest subset. Join only explicit span IDs.
        spans = {}
        for resource in record.get("resourceSpans", []):
            attributes = {
                a["key"]: a["value"].get("stringValue")
                for a in resource.get("resource", {}).get("attributes", [])
            }
            service = attributes.get("service.name")
            if not service:
                raise ValueError("OTLP resource requires service.name.")
            environment = attributes.get("deployment.environment.name")
            if environment and environment != self.source.environment:
                raise ValueError("OTLP resource environment differs from configured source.")
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    key = (span["traceId"], span["spanId"])
                    if key in spans:
                        raise ValueError("Duplicate trace/span ID in export.")
                    if len(spans) >= 2000:
                        raise ValueError("OTLP export exceeds the 2000-span record budget.")
                    seconds = int(span["startTimeUnixNano"]) / 1_000_000_000
                    timestamp = datetime.fromtimestamp(seconds, UTC).isoformat()
                    spans[key] = (service, span, utc(timestamp))
        if not spans:
            raise ValueError("OTLP export contains no supported spans.")
        for (trace_id, _), (service, span, timestamp) in spans.items():
            self.component(service, timestamp)
            parent_id = span.get("parentSpanId")
            parent = spans.get((trace_id, parent_id))
            if parent_id and not parent:
                self.result.warnings.append("Unresolved span parent; no dependency inferred.")
            if not parent or parent[0] == service:
                continue
            kinds = {
                "SPAN_KIND_CLIENT": 3,
                "SPAN_KIND_SERVER": 2,
                "SPAN_KIND_PRODUCER": 4,
                "SPAN_KIND_CONSUMER": 5,
            }
            pair = (
                kinds.get(parent[1].get("kind"), parent[1].get("kind")),
                kinds.get(span.get("kind"), span.get("kind")),
            )
            if pair not in {(3, 2), (4, 5)}:
                continue
            observed_ms = epoch_ms(timestamp)
            # Aggregate repeated observations per source/pair/minute, with exact first/last bounds.
            self.edge(
                "DEPENDS_ON",
                self.component_id(parent[0]),
                self.component_id(service),
                "Component",
                "Component",
                method="observed_trace",
                observed_at=timestamp,
                valid_from_ms=observed_ms,
                valid_to_ms=observed_ms + 15 * 60_000,
                identity=str(observed_ms // 60_000),
                trace_id=trace_id,
                parent_span_id=parent_id,
                span_id=span["spanId"],
            )
