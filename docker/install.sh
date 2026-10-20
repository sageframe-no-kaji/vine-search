#!/bin/sh
# Run from the directory containing compose.yaml and docker/seccomp-chromium.json.
set -eu
cd "$(dirname "$0")/.."
docker compose version >/dev/null
replace_image=0
if [ "${VINE_SEARCH_IMAGE+x}" = x ]; then
  [ -n "$VINE_SEARCH_IMAGE" ] || { printf '%s\n' 'VINE_SEARCH_IMAGE cannot be empty.' >&2; exit 1; }
  replace_image=1
fi
if [ -f .env ]; then
  # Compose parses its own dotenv format. Never execute configuration as shell code.
  configured_images=$(docker compose config --images)
  image=$(printf '%s\n' "$configured_images" | sort -u)
else
  image=${VINE_SEARCH_IMAGE:-ghcr.io/sageframe-no-kaji/vine-search:0.1.1}
  replace_image=1
fi
case "$image" in
  ''|-*|*[!a-zA-Z0-9._/:@-]*)
    printf '%s\n' 'The web and collector must use one valid image reference.' >&2
    exit 1
    ;;
esac
docker pull "$image"
if [ ! -f .env ]; then
  docker run --rm --user "$(id -u):$(id -g)" \
    --mount "type=bind,src=$PWD,dst=/install" \
    "$image" setup --directory /install
fi
# Persist the selection before startup, so later ordinary Compose commands use it.
# Python comes from the selected image; the host still needs only Docker and Compose.
docker run --rm -i --user "$(id -u):$(id -g)" \
  --env "VINE_SEARCH_INSTALL_IMAGE=$image" \
  --env "VINE_SEARCH_INSTALL_REPLACE=$replace_image" \
  --mount "type=bind,src=$PWD,dst=/install" \
  --entrypoint python "$image" - /install <<'PY'
import os
import re
import sys
import tempfile
from io import StringIO
from pathlib import Path
from dotenv.parser import parse_stream

directory = Path(sys.argv[1])
path = directory / ".env"
original = path.read_bytes()
bindings = list(parse_stream(StringIO(original.decode("utf-8"))))
present = any(binding.key == "VINE_SEARCH_IMAGE" for binding in bindings)
if present and os.environ["VINE_SEARCH_INSTALL_REPLACE"] != "1":
    raise SystemExit(0)
if any(binding.error for binding in bindings):
    raise SystemExit("Cannot update malformed .env; correct its syntax before installing.")
newline = "\r\n" if b"\r\n" in original else "\n"
assignment = "VINE_SEARCH_IMAGE=" + os.environ["VINE_SEARCH_INSTALL_IMAGE"] + newline
updated = []
inserted = False
for binding in bindings:
    if binding.key == "VINE_SEARCH_IMAGE":
        # Keep separators, and never mistake a line inside a quoted value for a key.
        prefix = re.match(r"[ \t\r\n]*", binding.original.string).group()
        updated.append(prefix)
        if not inserted:
            updated.append(assignment)
            inserted = True
    else:
        updated.append(binding.original.string)
if not inserted:
    if updated and not updated[-1].endswith(("\n", "\r")):
        updated.append(newline)
    updated.append(assignment)
contents = "".join(updated).encode("utf-8")
if contents != original:
    descriptor, temporary = tempfile.mkstemp(prefix=".env.install-", dir=directory)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(contents)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
PY
VINE_SEARCH_IMAGE="$image" docker compose config --quiet
VINE_SEARCH_IMAGE="$image" docker compose pull
VINE_SEARCH_IMAGE="$image" docker compose up -d --no-build --wait
printf '%s\n' 'VineSearch is running. Default dashboard: http://127.0.0.1:8765'
