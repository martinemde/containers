# Rethink main publisher handoff

Prepared locally on 2026-11-11. No push, remote mutation, deployment or activation.
The existing live Quadlet publication described in Beelink's conversion runbook
is unchanged. This adds automatic publication for future application main merges.

## Contract

- Canonical workflow: `.github/workflows/publish-rethink.yml` in `martinemde/containers`.
- Events: schedule every 10 minutes, manual dispatch, relevant publisher main push.
- Select exact current public `martinemde/rethink` main only when its trusted
  `.github/workflows/ci.yml` push/main run completed successfully.
- Download exact commit archive, compute SHA256, supply revision/hash build args.
- Build linux/amd64, run source tests/build and offline smoke, push same tested image.
- Discovery tag: `ghcr.io/martinemde/rethink:run-<run_id>-<run_attempt>`.
- OCI source identifies containers; OCI revision identifies publisher commit;
  `io.github.martinemde.rethink.revision` identifies exact application commit.
- Consumer independently verifies run, tag/digest, labels and application CI.
- Logical release identity is application/publisher revision pair. Consumer skips
  same-pair redeployment after health verification. An intentional rebuild release
  requires a publisher main commit; non-snapshot Alpine packages can change digests.
- No app repository changes or cross-repository secrets required.

## Changed files

- `.github/workflows/publish-rethink.yml` (new): sole canonical publisher.
- `.github/workflows/build.yml`: retains PR/main validation; removes old publication;
  adds source-selection tests.
- `rethink/source.py` (new): public API/CI/source archive selection.
- `rethink/test_source.py` (new): trust rejection and archive selection tests.
- `rethink/Containerfile`: revision/archive hash build args, immutable local defaults.
- `rethink/test.sh`: explicit expected application revision parameter.
- `rethink/README.md`, `README.md`: workflow and consumer contract.
- `docs/rethink-main-publisher.md` (this handoff).

Pre-existing unrelated tailscale/docs deletions and project.md were not changed.

## Validation

Passed:

```sh
python3 -m unittest discover -s containers/rethink -p test_source.py -v
python3 containers/rethink/source.py
podman build --platform linux/amd64 -f containers/rethink/Containerfile -t localhost/rethink-publisher-contract containers/rethink
env CONTAINER_ENGINE=podman sh containers/rethink/test.sh localhost/rethink-publisher-contract e96ae725850019c59547c360ec757957b9fa9ddb
podman image inspect localhost/rethink-publisher-contract
git -C containers diff --check
```

Three source-selection tests passed, including rejection of stale/foreign/PR/
failed/wrong-workflow runs before source archive download. Live read-only helper
selected app `e96ae725850019c59547c360ec757957b9fa9ddb`, CI run `42976681528`,
archive SHA256 `e2bb72b44dc78c24d27dfc72a36b02da9e4e33f8e12dd4ba2f8d12e2af4cf0ef`.
Full Podman build completed successfully, including application tests and build.
Offline network-none smoke passed. JSON image inspection confirmed exact full
application revision label. Local image retained as
`localhost/rethink-publisher-contract`; not pushed.

`actionlint` is unavailable; workflow reviewed but not executed on GitHub.
Schedule is best-effort, not a 10-minute SLA. Current failed/pending app main blocks
publication rather than falling back to an earlier application revision.
