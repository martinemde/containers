# Containers

Container builds for services, including applications intended for LXC deployment.
Each image has its own folder, `Containerfile`, and offline `test.sh`. Tailscale
wraps an upstream image; Rethink builds a pinned public application source.
This repository does not verify or configure a running service.
There are no host addresses, runtime settings, or secrets here.

Base images must come from the first-party upstream publisher or an official
Linux distribution. Arbitrary third-party repackaged images are not allowed.
Every base keeps its upstream tag and an immutable digest.

## Build and publication

Pull requests build every matrix image and run its `test.sh` without network
access. Rethink also runs its source tests during the build. Updates to `main`
publish each same tested image to `ghcr.io/martinemde/<image>`, tagged
`main` and `sha-<full commit SHA>`. The initial scope is **linux/amd64** only.
The workflow adds OCI source and revision labels, reports the registry digest,
and saves a `<image>-digest` artifact containing the immutable image reference.
The first GHCR package publication may need its visibility changed to public.

The Tailscale wrapper inherits the upstream entrypoint, command, and image configuration.
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

## Application build sources

- [Rethink](rethink/README.md) builds the public fork at an exact verified commit.
- [Collector migration status](docs/collector-migration.md) records why the three
  localhost collector recipes cannot yet become public, pinned builds.

Build contexts must contain only reviewed recipes and code. Never build directly
from a private working tree containing exports, `.env`, credentials, archives,
or databases. Rethink downloads only its pinned public source; its deny-all
context rules exclude all local application files. Runtime config, state, secrets,
and deployment automation belong elsewhere. Publication does not authorize or
perform a runtime migration.

Source commits and base digests are immutable. Registry packages installed by
`apk` are not snapshot-pinned, so Rethink is not claimed byte-reproducible; consume
its published image digest. Source revision/hash updates require explicit review;
Renovate currently manages image bases and actions, not application source pins.
