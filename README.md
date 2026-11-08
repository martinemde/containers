# Containers

Thin wrappers for third-party images used by my services. Each source has its own
folder and `Containerfile`. The first image is Tailscale, selected from a declared
Matrix sidecar; this repository does not verify or configure a running service.
There are no host addresses, runtime settings, or secrets here.

## Build and publication

Pull requests build and run `tailscale --version` without network access. Updates
to `main` publish the same tested image to `ghcr.io/martinemde/tailscale`, tagged
`main` and `sha-<full commit SHA>`. The initial scope is **linux/amd64** only.
The workflow adds OCI source and revision labels, reports the registry digest,
and saves a `tailscale-digest` artifact containing the immutable image reference.
The first GHCR package publication may need its visibility changed to public.

The wrapper inherits the upstream entrypoint, command, and image configuration.
`stable` is the upstream tag; its manifest digest fixes the actual base bytes.
The upstream version label remains inherited, not a new application version.
Renovate discovers every `Containerfile` and proposes reviewed updates using the
shared preset pinned to `v1.0.0`. Automerge is disabled for this initial proof.
Action references are also pinned and managed by Renovate.

Publication is **not live deployment**. Nothing here restarts a service. A future
`deploy-main` consumer should verify a successful trusted `main` run and consume
the digest artifact (an `image@sha256:...` reference), not the mutable `main` tag.
No deployment webhook is installed.

Local smoke test (Docker or Podman):

```sh
podman build --platform linux/amd64 -f tailscale/Containerfile -t localhost/tailscale-test tailscale
podman run --rm --network none --entrypoint tailscale localhost/tailscale-test --version
```
