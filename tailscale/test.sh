#!/bin/sh
set -eu
engine=${CONTAINER_ENGINE:-docker}
"$engine" run --rm --network none --entrypoint tailscale "$1" --version
