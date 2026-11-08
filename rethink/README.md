# Rethink application image

Builds public first-party fork `https://github.com/martinemde/rethink` at
`a4f24a49cec14d33993cb59e01108a917f99a728` (reviewed `main` revision). Archive SHA256:
`9a12340838a1f2885c9e682ba7d1bc6244e84ece730ed2d507a1ae69bee38dad`.
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
metadata together after reviewing fork changes. Do not replace the pin with a
moving branch URL. Do not send private sources via build arguments or tokens.

## Main source update proposals

The `Propose Rethink main source update` workflow runs hourly (minute 17 UTC)
and supports manual dispatch. It reads only public `martinemde/rethink` main,
requires a successful `ci.yml` **push on main** run for that exact SHA in that
repository, then downloads its commit archive and computes the checksum. It never
executes the downloaded source. Commit URL, checksum and version metadata remain
pinned together in this repository; no application recipe or source is published
elsewhere. PR heads and feature branches are not source candidates.

The updater opens a PR using the repository's short-lived `GITHUB_TOKEN`; it does
not auto-merge. Existing update PRs are left untouched. Because token-created PRs
do not trigger `pull_request` workflows, it explicitly dispatches `build.yml` on
the generated branch. That run builds/tests without publishing. Review that run
and the source diff before merging. The ordinary containers main push builds,
tests and publishes the merged recipe; publication is not live deployment.

One-time settings: allow GitHub Actions to create pull requests in **containers**;
no personal token or deployment credentials are needed. Scheduled runs can be
delayed by GitHub; dispatch manually for an immediate proposal after successful
source-main CI. If PR creation or dispatch fails, fix settings and explicitly
rerun/dispatch the existing branch build; do not infer success from an open PR.

**Current prerequisite:** fork `ci.yml` only triggers pushes to `master`, not
`main` (verified 2026-11-08). Enable source main push CI in the source repository
before relying on this updater. Until then new revisions fail closed. PR #5 is
still open; its future main merge SHA is intentionally not guessed or replaced by
its feature head. The existing pin is unchanged in this preparation.

## Validation and security review

Local linux/amd64 Podman build and both offline smoke checks passed on 2026-11-08.
All 1,319 source tests passed. `npm audit --omit=dev` on the preserved lockfile
reports two production advisories: high `body-parser`
[GHSA-27r3-jxmh-p828](https://github.com/advisories/GHSA-27r3-jxmh-p828) and
moderate `qs` [GHSA-6pq8-jhm2-2vcw](https://github.com/advisories/GHSA-6pq8-jhm2-2vcw).
No automatic lockfile changes were made. Review/fix these in the source fork and
update the immutable source pin before authorizing live deployment. Passing
build/smoke tests is not a security approval.
