#!/bin/sh
set -eu
engine=${CONTAINER_ENGINE:-docker}
image=$1
version=$("$engine" image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
test -n "$version"
container=
cleanup() { [ -z "$container" ] || "$engine" rm -f "$container" >/dev/null; }
trap cleanup EXIT HUP INT TERM
[ "$("$engine" image inspect "$image" --format '{{.Config.User}}')" = '994:987' ]
container=$("$engine" run -d --network none --read-only --cap-drop ALL   --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid   --tmpfs /var/lib/agent-feeds-nui:rw,noexec,nosuid,mode=1777 "$image")
# Probe only container-local loopback; no host listeners or broker connection.
"$engine" exec -e EXPECTED_VERSION="$version" "$container" sh -ec '
  for attempt in $(seq 1 60); do
    if wget -qO /tmp/health http://127.0.0.1:31311/health; then break; fi
    sleep 1
  done
  grep -q OK /tmp/health
  wget -qO /tmp/about http://127.0.0.1:31311/api/about
  grep -Fq "\"current_version\":\"$EXPECTED_VERSION\"" /tmp/about
  wget -qO /tmp/index http://127.0.0.1:31311/
  grep -q "assets/" /tmp/index
  asset=$(grep -oE "/assets/[^\"]+\.js" /tmp/index | head -n 1)
  test -n "$asset"
  wget -qO /tmp/asset "http://127.0.0.1:31311$asset"
  test -s /tmp/asset
  test -f /var/lib/agent-feeds-nui/MANIFEST
'
"$engine" stop --time 10 "$container" >/dev/null
[ "$("$engine" inspect "$container" --format '{{.State.ExitCode}}')" = 0 ]
