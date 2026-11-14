# Caddy

Two linux/amd64 images isolate the Caddy upgrade from the plugin swap:

- `plain` target: official Caddy 2.11.9 binary, without the plugin.
- Default `runtime` target: Caddy 2.11.9 with
  `github.com/tailscale/caddy-tailscale` at
  `de41b249af4fd2083612c3b2303197e92787d1c5`.

The plugin requires Caddy >=2.10.2 and Go >=1.26.5. Keeping 2.6.2 would require
an obsolete plugin revision or overriding dependency requirements. Instead,
2.11.9 is the current stable upstream release (2026-11-05). xcaddy explicitly
selects 2.11.9 and the build asserts the resulting executable version. The
2.11.9 official builder provides Go 1.27; compilation uses CGO_ENABLED=0 and
bounded parallelism (GOMAXPROCS=2, GOFLAGS=-p=2).

Both variants preserve the existing Debian 13-slim filesystem digest,
UID/GID 1109:1109, XDG paths, executable path, entrypoint and default command.
Only the Caddy binary differs between variants. Neither image includes a
Caddyfile, trust-store changes, site paths, credentials, or live service config.
The Debian digest is the existing amd64 manifest; these recipes target amd64.

## Publisher and pin evidence

All bases are official Docker Library images, with tags and immutable digests.
The [official-images Caddy manifest](https://github.com/docker-library/official-images/blob/master/library/caddy)
identifies `github.com/caddyserver/caddy-docker` as its source, maintained by
Caddy upstream. At verification the source revision was
`d322e6686bbce5622d98a04c84fadd43b5eb8c58`.
The [Debian manifest](https://github.com/docker-library/official-images/blob/master/library/debian)
identifies the official Debian image source. Digests were verified through the
Docker Registry v2 API. The runtime Debian digest is deliberately unchanged.

## Local checks

From the repository root:

```sh
podman build --platform linux/amd64 --target plain -f caddy/Containerfile -t localhost/caddy-plain-test caddy
CONTAINER_ENGINE=podman sh caddy/test.sh localhost/caddy-plain-test plain
podman build --platform linux/amd64 -f caddy/Containerfile -t localhost/caddy-plugin-test caddy
CONTAINER_ENGINE=podman sh caddy/test.sh localhost/caddy-plugin-test plugin
```

`test.sh IMAGE [plain|plugin]` defaults to `plugin` and Docker. Tests run offline,
read-only, without capabilities or new privileges, using synthetic HTTP-only
input. They check the executable, module presence/absence, Caddyfile adaptation,
and runtime defaults. They do not register a Tailscale node, issue a certificate,
or verify a live deployment. A successful build is not runtime acceptance.

## Publication and rollout boundary

`publish-caddy.yml` builds, tests, publishes, and attests the exact tested
amd64 images as `ghcr.io/martinemde/caddy-plain` and
`ghcr.io/martinemde/caddy-plugin`. Run tags identify the workflow run/attempt;
version/main tags are convenience handles. Each variant emits a digest artifact.
Deployment must consume a verified immutable digest, not a mutable tag.
The workflow performs no deployment.

First upgrade a consumer to the plain 2.11.9 image with its existing config and
verify it. Only then swap to the same-version plugin image, without config
changes. Tailnet behavior is a separate, explicitly configured runtime change.
