# Rethink application image

Builds public first-party fork `https://github.com/martinemde/rethink` at
`e96ae725850019c59547c360ec757957b9fa9ddb` (`main`, verified with `gh api` on
2026-11-11). Archive SHA256:
`e2bb72b44dc78c24d27dfc72a36b02da9e4e33f8e12dd4ba2f8d12e2af4cf0ef`.
The source archive is verified before extraction. No local source is copied.
`npm ci` uses that revision's `package-lock.json`; source tests and compilation
must pass before production dependencies and output enter the runtime stage.

Both stages use official `docker.io/library/alpine:3.24` pinned to its registry
manifest digest. Publisher evidence: Docker Official Images' `library/alpine`
entry identifies Alpine maintainer Natanael Copa and
`https://github.com/alpinelinux/docker-alpine.git`. This is not a third-party
application image. The two-stage build follows the fork's existing Dockerfile;
no new application dependencies are added. Alpine packages are not snapshot-pinned.

The upstream default command, public example config, data path and ports are
preserved. No host runtime configuration or credentials are included. Offline
smoke tests inspect syntax, dependency resolution and compiled version metadata;
they never start the app, device connections, listeners or cloud transports.
Deployment permissions/users, data ownership, configuration and network access
remain a separate operator decision. No deployment is performed here.

```sh
podman build --platform linux/amd64 -f rethink/Containerfile -t localhost/rethink-test rethink
podman run --rm --network none --entrypoint node localhost/rethink-test --check dist/rethink-cloud.js
```

`test.sh IMAGE` uses Docker in CI. Update source commit, archive hash and version
metadata and `io.github.martinemde.rethink.revision` together after reviewing fork changes. Do not replace the pin with a
moving branch URL. Do not send private sources via build arguments or tokens.

## Validation and security review

The image CI performs linux/amd64 build and offline smoke checks before publishing.
The pinned source passed fork CI on Node 20 and 24; this image pipeline reruns source tests. `npm audit --omit=dev` on the preserved lockfile
reports two production advisories: high `body-parser`
[GHSA-27r3-jxmh-p828](https://github.com/advisories/GHSA-27r3-jxmh-p828) and
moderate `qs` [GHSA-6pq8-jhm2-2vcw](https://github.com/advisories/GHSA-6pq8-jhm2-2vcw).
No automatic lockfile changes were made. Review/fix these in the source fork and
update the immutable source pin before authorizing live deployment. Passing
build/smoke tests is not a security approval.
