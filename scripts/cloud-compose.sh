#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export DOCKER_CONFIG="${DOCKER_CONFIG:-/workspace/.docker}"
mkdir -p "$DOCKER_CONFIG"
exec docker compose -f compose.yaml -f compose.cloud.yaml "$@"
