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

Pull requests and publisher-repository `main` pushes validate both existing image
contexts; Rethink builds the reviewed default source pin and run offline smoke tests in `build.yml`. They do not publish images.

`publish-rethink.yml` is the canonical publisher. It runs every **10 minutes**,
on manual dispatch, and on relevant publisher `main` changes. It reads public
`martinemde/rethink` main and requires a completed successful push/main run of
`.github/workflows/ci.yml` for that exact commit, in that same repository (not a
fork or PR). If current main has not passed CI, publication fails until it does.
No second source-pin PR or cross-repository token is needed after an app merge.
Scheduled Actions can be delayed or disabled by GitHub; this is not a 10-minute SLA.

The publisher downloads that exact public commit archive, computes its SHA256,
and passes both source revision and archive hash to the Containerfile. Source
tests and compilation run during the build. It then runs offline smoke tests and
pushes the **same tested linux/amd64 image** to
`ghcr.io/martinemde/rethink:run-<run_id>-<run_attempt>`. Each attempt has its own tag,
including rebuilds of the same app with changed bases or publisher recipes. The
workflow always publishes; it never reports successful no-op runs without tags.
BuildKit cache avoids needless rebuilding when inputs are unchanged.

Labels bind `org.opencontainers.image.source` to this repository,
`org.opencontainers.image.revision` to the publisher commit, and
`io.github.martinemde.rethink.revision` to the application commit. The workflow
reports the immutable registry digest and saves a `rethink-digest` artifact.
The first GHCR package publication may need its visibility changed to public.

Publication is **not live deployment**. Nothing here restarts a service. A
consumer must select a successful trusted `publish-rethink.yml` run on publisher
main (schedule, workflow_dispatch or push), resolve its exact run/attempt tag,
check all three labels and successful app push/main CI, then deploy only the
resolved `image@sha256:...` reference. Tags are discovery handles, not immutable
registry enforcement. The consumer must independently validate provenance.
The application/publisher revision pair is the logical release identity: a
controller should verify current health and skip redeployment when both already
match its active release. Scheduled rebuilds can otherwise produce new digests
without a merge because Alpine packages are not snapshot-pinned. An intentional
rebuild deployment therefore requires a new publisher main commit.
No deployment webhook is installed; no runtime configuration or secrets belong here.

Renovate manages pinned Containerfile bases and actions using the shared preset
`v1.0.0`. Automerge remains disabled. Application source follows CI-verified main
only in the canonical publication workflow; local/PR defaults remain pinned.

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
its published image digest. The canonical publisher follows CI-verified application
main; Renovate manages image bases and actions, not application source pins.
