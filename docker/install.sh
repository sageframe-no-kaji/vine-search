#!/bin/sh
# Run from the directory containing compose.yaml and docker/seccomp-chromium.json.
set -eu
cd "$(dirname "$0")/.."
image=${VINE_SEARCH_IMAGE:-ghcr.io/sageframe-no-kaji/vine-search:0.1.0}
docker compose version >/dev/null
docker pull "$image"
if [ ! -f .env ]; then
  docker run --rm --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$PWD,dst=/install" \
    "$image" setup --directory /install
fi
VINE_SEARCH_IMAGE="$image" docker compose config --quiet
VINE_SEARCH_IMAGE="$image" docker compose pull
VINE_SEARCH_IMAGE="$image" docker compose up -d --no-build --wait
printf '%s\n' 'VineSearch is running. Default dashboard: http://127.0.0.1:8765'
