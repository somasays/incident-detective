"""Continuously construct Neo4j facts from local append-only source exports."""

import argparse
import json
import time
from pathlib import Path

from ingestion.models import Sources
from ingestion.runner import poll_once
from ingestion.store import GraphWriter
from knowledge.db import Database
from knowledge.ontology import ensure_schema


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--watch", action="store_true", help="Poll continuously; Ctrl-C to stop")
    parser.add_argument("--interval", type=float, default=2)
    args = parser.parse_args()
    if not 0.2 <= args.interval <= 60:
        parser.error("--interval must be between 0.2 and 60 seconds")
    config = Sources.load(args.sources)
    with Database() as database:
        database.wait_ready()
        ensure_schema(database)
        writer = GraphWriter(database, config.namespace)
        first_poll = True
        try:
            while True:
                reports = poll_once(writer, config.sources)
                if first_poll or any(r.get("records") or r.get("error") for r in reports):
                    print(
                        json.dumps({"namespace": config.namespace, "sources": reports}), flush=True
                    )
                first_poll = False
                if not args.watch:
                    return int(any("error" in r for r in reports))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("Stopped. Committed source cursors are stored in local Neo4j.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
