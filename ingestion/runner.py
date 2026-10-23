"""Bounded append-only JSONL polling, crash recovery and source-level backpressure."""

import hashlib
import json

from neo4j.exceptions import DriverError, Neo4jError

from ingestion.adapters import Adapter
from ingestion.models import digest

MAX_LINE_BYTES = 1_048_576
BATCH_RECORDS = 50


def fingerprint(handle, offset):
    position = handle.tell()
    handle.seek(0)
    prefix = handle.read(min(offset, 4096))
    handle.seek(max(0, offset - 256))
    tail = handle.read(min(offset, 256))
    handle.seek(position)
    return hashlib.sha256(prefix + tail).hexdigest()


def poll_source(writer, source):
    state = writer.state(source)
    config_hash = digest(source.model_dump(mode="json"))
    if state.get("config_hash", config_hash) != config_hash:
        raise ValueError("Source configuration changed. Use a new source ID.")
    mutations, offset, line = [], state["offset"], state.get("line", 0)
    warnings = []
    with source.path.open("rb") as handle:
        handle.seek(0, 2)
        if handle.tell() < offset:
            raise ValueError(
                "Source was truncated. Preserve it and configure a new source file/ID."
            )
        if offset and fingerprint(handle, offset) != state.get("fingerprint"):
            raise ValueError(
                "Processed source bytes changed. Cursor preserved; use a new source ID."
            )
        handle.seek(offset)
        for _ in range(BATCH_RECORDS):
            start = handle.tell()
            raw = handle.readline(MAX_LINE_BYTES + 1)
            if len(raw) > MAX_LINE_BYTES:
                raise ValueError(f"Line {line + 1} exceeds 1 MiB; cursor preserved.")
            if not raw or not raw.endswith(b"\n"):
                # A writer can be midway through a record. Re-read it on the next poll.
                handle.seek(start)
                break
            line += 1
            if raw.strip():
                try:
                    record = json.loads(raw)
                    if not isinstance(record, dict):
                        raise ValueError("Expected a JSON object")
                    mutation = Adapter(writer.namespace, source).convert(record, line)
                except (ValueError, KeyError, TypeError, OverflowError, AttributeError) as exc:
                    raise ValueError(f"Invalid {source.id} line {line}: {exc}") from exc
                mutations.append(mutation)
                warnings.extend(mutation.warnings)
        new_offset = handle.tell()
        if new_offset != offset:
            writer.commit(
                source,
                state,
                mutations,
                {
                    "offset": new_offset,
                    "line": line,
                    "fingerprint": fingerprint(handle, new_offset),
                },
            )
        handle.seek(0, 2)
        pending = handle.tell() - new_offset
    return {
        "source": source.id,
        "records": len(mutations),
        "offset": new_offset,
        "pending_bytes": pending,
        "warnings": sorted(set(warnings)),
    }


def poll_once(writer, sources):
    reports = []
    for source in sources:
        try:
            reports.append(poll_source(writer, source))
        except (OSError, ValueError, DriverError, Neo4jError) as exc:
            reports.append({"source": source.id, "error": str(exc)})
    return reports
