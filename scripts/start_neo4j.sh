#!/usr/bin/env bash
# APOC Core ships inside the pinned Neo4j image. Copy it without a network download.
set -euo pipefail
cp /var/lib/neo4j/labs/apoc-*-core.jar /var/lib/neo4j/plugins/
exec /startup/docker-entrypoint.sh "$@"
