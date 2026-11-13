# NUI

Builds [nats-nui/nui](https://github.com/nats-nui/nui) web from public source,
not from private host binaries or state. The reviewed default is **0.9.3**,
commit `ba291a34430c0bdd0d2b45e070a153e62a45289c`. No loopback listener patch is applied:
upstream listens on all container interfaces, TCP **31311**. Deployment must
isolate the listener; there is no added authentication layer in this recipe.

## Fixed build inputs

`Containerfile` pins the version, source commit, release archive SHA256 and every
base digest. The build verifies the archive checksum and checks that the GitHub
version tag points to the recorded commit. The current tag is lightweight;
annotated tags require review of this validation before use. GitHub API failure
or rate limiting fails the build closed. Go uses `go.sum`, `go mod verify`,
`-mod=readonly`, `GOTOOLCHAIN=local`, `CGO_ENABLED=0` and `-trimpath`.
Frontend builds use `npm ci --ignore-scripts`; downloaded optional SWC/esbuild
packages provide the native frontend tools without install scripts.

Upstream's npm lock is inconsistent: npm reports missing `msw@2.15.0` and an
invalid `rettime@0.11.7` for a `^0.11.12` requirement. The committed
`package-lock.json` is a reviewed overlay, generated from upstream's lock with
`npm install --package-lock-only --ignore-scripts --no-audit --no-fund` in the
exact pinned Node image. It adds the missing nested msw peer, changes rettime to
0.11.12, and updates peer/optional metadata. No direct dependency specification
is changed. The cached private Bun lock is not an input.

All bases are official Docker images, verified against the Docker Official
Images publisher records on 2026-11-13:
- [Go](https://github.com/docker-library/official-images/blob/master/library/golang),
  maintained by Docker Library, source `docker-library/golang`.
- [Node](https://github.com/docker-library/official-images/blob/master/library/node),
  maintained by the Node.js Docker Team, source `nodejs/docker-node`.
- [Alpine](https://github.com/docker-library/official-images/blob/master/library/alpine),
  maintained by Alpine, source `alpinelinux/docker-alpine`.

This is a rebuildable recipe with immutable source, dependency integrity locks,
and pinned toolchain/base inputs, **not a claim of byte-identical OCI images**.
Network package retrieval is still required; upstream artifact availability and
build metadata can affect rebuilds. No `apk` packages are resolved at build time.
Consume the published image by digest.

## Build and test

```sh
podman build --platform linux/amd64 -f nui/Containerfile -t localhost/nui-test nui
CONTAINER_ENGINE=podman sh nui/test.sh localhost/nui-test
```

Smoke tests run the actual listener and frontend with no external network,
read-only root, all capabilities dropped and no host port. They check health,
version, HTML, a compiled JS asset, persistent database creation and graceful
shutdown. `/api/about` tries an upstream update lookup, which fails harmlessly
with networking disabled. This is not a live NATS/authentication/state migration
test. The image defaults are:

- UID:GID `994:987` (existing deployment ownership contract).
- Working directory `/opt/agent-feeds/nui`.
- Database `/var/lib/agent-feeds-nui` (mount a writable owned volume).
- CLI contexts `/etc/agent-feeds/nui-contexts` (mount read-only at runtime).
- Optional schema directory `/opt/agent-feeds/nui/protoschemas/default`.

No credentials, state, hostnames or deployment settings enter the build context.
The deny-all context permits only `Containerfile` and the lock overlay.

## Publication and updates

`build.yml` builds and smoke-tests PRs. `publish-nui.yml` runs only on publisher
main pushes affecting NUI and manual dispatch on main. It builds and tests once,
then pushes **that same image** to `ghcr.io/martinemde/nui:run-<id>-<attempt>`,
`:0.9.3` (the image version), and `:main`. All are mutable discovery tags;
production uses `ghcr.io/martinemde/nui:0.9.3@sha256:...`. Labels record publisher
source/revision and `io.github.martinemde.nui.revision` for application source.
The workflow records the immutable reference in the summary and `nui-digest`
artifact. Initial GHCR publication may require making the package public.
Publication does not deploy or migrate runtime state. Until merged and published,
there is no registry digest to place into a deployment.

Renovate proposes base/tag/digest and GitHub Actions changes. A regex manager
also proposes upstream NUI version changes. A version-only update deliberately
fails archive checksum validation: review the tag's commit, replace source
revision/checksum, refresh the overlay only if necessary, and run build/smoke
before approval. This prevents a version bump from silently resolving new
unlocked dependencies or mislabelling old source. Automerge is disabled.
Deployment Renovate can track the versioned GHCR tag and propose its digest
rebuilds independently; source version upgrades still need this reviewed build.
