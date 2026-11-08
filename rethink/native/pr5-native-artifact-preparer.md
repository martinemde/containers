# Native main artifact preparation — controller only

The historical filename `prepare-pr5-native.py` is retained for callers. There is
no PR5 identity gate. This preparer has no target, SSH, OCI or deployment calls.
It prepares native `dist` only; a successful manifest is not deployment approval.

## Trust and immutable identity

The preparer resolves `martinemde/rethink` main once and saves its full SHA.
It requires the active `.github/workflows/ci.yml` GitHub workflow and a completed,
successful `push` run on `main` at that exact SHA. It verifies workflow ID/path,
event, branch, SHA, repository and head-repository identity. PR runs, other
workflows, branch builds and successful runs for other SHAs do not qualify.
If CI has not finished successfully, preparation fails before allocating output
or running npm. Retry later; no fallback to an earlier green commit.

By default the captured main SHA is the build identity. Optional `--revision`
accepts a full SHA in captured main history, for an explicitly ordered rollout.
The preparer requests GitHub compare `<revision>...<captured-main>` and requires
`ahead` or `identical`, with both base and merge-base SHA equal to the requested
revision (`identical` also requires equality with main). Diverged/nonancestor
revisions fail before workspace allocation. Trusted push/main CI is still
required for the exact selected revision. Compare evidence is saved and hashed
as `main-ancestry.json`; `main.json` continues to describe captured current main.
This selects an immutable historical main build; it never rewinds main.

Once selected, that SHA remains the build identity even if main advances. The
source archive URL uses the full SHA, never a branch name. No later main lookup
or PR merge identity check exists. A cancelled CI run is not success. Only the
first 100 matching runs are considered; absence fails closed.

The CI trigger fix was merged. Successful exact-revision push/main CI remains
mandatory for every release. No automatic image or OCI runtime is involved.

## Usage

Review the captured main source before running npm scripts. Use an isolated,
unprivileged controller with no target mounts or production credentials and the
project's supported native Node/npm versions. The controller requires network
access to GitHub and npm; the guest need not download or build anything.

From the repository root:

```sh
python3 -m unittest discover -s rethink/native -p test_prepare_pr5_native.py -v
python3 rethink/native/prepare-pr5-native.py --help
umask 077
python3 rethink/native/prepare-pr5-native.py \
  --package-sha256 "$CURRENT_PACKAGE_SHA256" \
  --lock-sha256 "$CURRENT_LOCK_SHA256" \
  --output "$BUILD_OUTPUT"
```

Required variables are approved current installed manifest hashes and a new
private output directory. Previously observed package hash:
`c20df55c835768bd425aa5fc6b3d234e2764bd4ba8cf94eaa8c7b8cea6a63a0a`;
lock hash: `599e59e87a093010ca0b852ee68f324cd9863c62b787dadee47651acebc708a2`.
These are historical known values, not a live baseline or embedded authorization.
Revalidate on the intended target (CT120), not by assuming CT117 equals CT120.

The preparer rejects unsafe source archives and prebuilt dist/node_modules,
compares both manifests byte-for-byte by hash, then runs:

1. `npm ci --ignore-scripts --engine-strict --no-audit --no-fund`
2. `npm test`
3. `npm run check`
4. `GIT_REVISION=<captured full SHA> npm run build`

It rechecks manifests after the build and verifies the seven-character baked
revision in `dist/util/version.js`; the full SHA is retained in the manifest.
Changed dependencies fail closed. No guest dependency-upgrade path is supplied.

`manifest.json` is written last. Schema 1 records `repo`, `commit`, `workflow_id`,
`ci_run_id`, native tool versions, commands, preparer hash, both manifest hashes,
every dist file hash and SHA256 of `source.tar.gz`, `dist.tar.gz`, `build.log`,
`main.json`, `workflow.json`, `ci-runs.json`. Dist file paths are relative to dist.
Tar metadata and gzip timestamps are normalized. This is deterministic packaging
of identical bytes, not a claim of reproducible builds across native toolchains.
Keep all evidence private. Hashes alone are not signatures or target approval.

## CT120 connection and missing target transaction

See `plain-lxc-pipeline.md`. The preparer deliberately does not contact a guest.
The controller must bind the manifest/source/dist hashes and captured full SHA
to a reviewed CT120 target transaction and its expected-current baseline.
Never send `main`, an image tag or a short revision as the target identity.
Do not use the historical helper's optional online npm/upgrade branch.

The included `native_target.py` implements a target transaction: preflight identities before service stops,
preserve config/state/certificates/dependencies, switch verified native dist,
restore only the original enabled recorder set and append identities, verify
health and exact release, and retain explicit recovery evidence. No automatic
rollback after candidate start: state/discovery changes can make it unsafe.
No appliance commands, broad HA/MQTT reloads, extra observers, guest confinement
changes, or state rewinds are part of artifact preparation.

Assumptions/constants: repository remains `martinemde/rethink`, branch `main`,
trusted workflow `.github/workflows/ci.yml`, and the existing version-writer
format. The PR number constant and supplied merge-commit gate were removed;
workflow path/identity and push/main CI gates replaced them. Tests are offline and do not alone certify a real source build or target
compatibility. Manual CT117 releases of PR4 then PR5 are recorded separately in
[the deployment result](plain-lxc-deployment-result.md). CT120 is not enrolled.
