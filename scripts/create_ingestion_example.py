"""Generate raw synthetic source exports, then append changes to exercise the real ingester."""

import argparse
import json
from datetime import datetime
from pathlib import Path


def append(path, record):
    with path.open("a") as handle:
        handle.write(json.dumps(record) + "\n")


def catalog(at, switched=False):
    services = [
        {
            "name": "web-api",
            "type": "service",
            "description": "Synthetic reporting endpoint.",
            "depends_on": ["report-store"],
        },
        {
            "name": "report-store",
            "type": "storage",
            "description": "Synthetic report storage.",
            "depends_on": ["loader"],
        },
        {
            "name": "loader",
            "type": "pipeline",
            "description": "Synthetic event validation.",
            "depends_on": ["backup-adapter"] if switched else [],
        },
        {
            "name": "source-adapter",
            "type": "connector",
            "description": "Synthetic source mapping.",
            "depends_on": [],
        },
    ]
    if switched:
        services.append(
            {
                "name": "backup-adapter",
                "type": "connector",
                "description": "Synthetic replacement source.",
                "depends_on": [],
            }
        )
    return {"observed_at": at, "services": services}


def trace_export():
    trace_id = "a" * 32
    nanos = str(int(datetime.fromisoformat("2026-10-23T10:40:00+00:00").timestamp()) * 10**9)

    def resource(service, span):
        return {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service}},
                    {"key": "deployment.environment.name", "value": {"stringValue": "local"}},
                ]
            },
            "scopeSpans": [{"spans": [{"traceId": trace_id, "startTimeUnixNano": nanos, **span}]}],
        }

    return {
        "resourceSpans": [
            resource("loader", {"spanId": "1" * 16, "name": "fetch events", "kind": 3}),
            resource(
                "source-adapter",
                {"spanId": "2" * 16, "parentSpanId": "1" * 16, "name": "serve events", "kind": 2},
            ),
        ]
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/input-lab"))
    parser.add_argument("--namespace", default="inputs-lab")
    parser.add_argument(
        "--stage", choices=["initial", "incident", "changed-topology"], required=True
    )
    args = parser.parse_args()
    directory = args.output
    directory.mkdir(parents=True, exist_ok=True)
    if args.stage == "initial":
        if (directory / "sources.json").exists():
            parser.error("Example already exists; use another output directory to start fresh.")
        sources = []
        for id, adapter in [
            ("service-catalog", "catalog"),
            ("trace-export", "otlp"),
            ("release-export", "deployments"),
            ("alert-export", "incidents"),
            ("application-logs", "logs"),
        ]:
            (directory / f"{adapter}.jsonl").touch(exist_ok=False)
            sources.append(
                {"id": id, "adapter": adapter, "environment": "local", "path": f"{adapter}.jsonl"}
            )
        (directory / "sources.json").write_text(
            json.dumps(
                {
                    "namespace": args.namespace,
                    "sources": sources,
                },
                indent=2,
            )
        )
        append(directory / "catalog.jsonl", catalog("2026-10-23T10:00:00Z"))
        append(directory / "otlp.jsonl", trace_export())
    elif args.stage == "incident":
        append(
            directory / "deployments.jsonl",
            {
                "id": "release-42",
                "service": "source-adapter",
                "timestamp": "2026-10-23T10:38:00Z",
                "version": "4.2.0",
                "description": "Changed customer ID mapping from integer to string.",
            },
        )
        append(
            directory / "incidents.jsonl",
            {
                "id": "alert-42",
                "service": "web-api",
                "timestamp": "2026-10-23T10:42:00Z",
                "summary": "Reporting requests fail",
                "severity": "SEV-1",
                "status": "open",
            },
        )
        for id, service, at, type, message in [
            (
                "schema-42",
                "loader",
                "10:41:00",
                "SCHEMA_MISMATCH",
                "customer_id is a string; loader expects integer.",
            ),
            ("http-42", "web-api", "10:42:00", "HTTP_500", "Reporting requests return HTTP 500."),
        ]:
            append(
                directory / "logs.jsonl",
                {
                    "id": id,
                    "service": service,
                    "timestamp": f"2026-10-23T{at}Z",
                    "severity": "ERROR",
                    "error_type": type,
                    "message": message,
                    "incident_id": "alert-42",
                    "incident_source": "alert-export",
                },
            )
    else:
        append(directory / "catalog.jsonl", catalog("2026-10-23T11:00:00Z", switched=True))
        append(
            directory / "incidents.jsonl",
            {
                "id": "alert-43",
                "service": "web-api",
                "timestamp": "2026-10-23T11:02:00Z",
                "summary": "Inspect changed topology",
                "severity": "SEV-3",
                "status": "open",
            },
        )
    print(
        f"Appended {args.stage} source records to {directory}. No graph nodes/edges were supplied."
    )


if __name__ == "__main__":
    main()
