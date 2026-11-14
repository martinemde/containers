#!/bin/sh
set -eu
engine=${CONTAINER_ENGINE:-docker}
image=${1:?usage: test.sh IMAGE [plain|plugin]}
variant=${2:-plugin}
case "$variant" in plain|plugin) ;; *) exit 2 ;; esac
run() {
    "$engine" run --rm -i --network none --read-only --cap-drop ALL \
        --security-opt no-new-privileges --tmpfs /tmp:rw,noexec,nosuid,size=16m \
        "$image" "$@"
}
run version | grep -E '^v2\.11\.9([[:space:]]|$)'
modules=$(run list-modules)
if [ "$variant" = plugin ]; then
    printf '%s\n' "$modules" | grep -Fx tailscale
    printf '%s\n' "$modules" | grep -Fx http.authentication.providers.tailscale
else
    if printf '%s\n' "$modules" | grep -Fx tailscale; then exit 1; fi
fi
# Synthetic HTTP-only input; no live service config, credentials or tailnet access.
printf ':8080 {\n respond "offline smoke test"\n}\n' | run adapt --adapter caddyfile --config /dev/stdin >/dev/null
if [ "$variant" = plugin ]; then
    printf ':8080 {\n bind tailscale/offline-smoke\n respond "offline smoke test"\n}\n' | run adapt --adapter caddyfile --config /dev/stdin >/dev/null
fi
config=$("$engine" image inspect "$image" --format '{{.Config.User}} {{json .Config.Entrypoint}} {{json .Config.Cmd}}')
test "$config" = '1109:1109 ["/usr/bin/caddy"] ["run","--config","/etc/caddy/Caddyfile","--adapter","caddyfile"]'
run environ | grep -Fx 'caddy.AppDataDir=/data/caddy'
run environ | grep -Fx 'caddy.AppConfigDir=/config/caddy'
