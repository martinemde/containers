# Native main release controller (manual, not armed)

`native_release.py` is a local controller entrypoint. It runs the reviewed
preparer, verifies the retained evidence and artifact bytes, and can send only a
bounded JSON request to CT117's dedicated forced-command SSH account. It does
not use Proxmox credentials, install target software, run npm on CT117, or enroll
CT120. There is no timer/webhook/job that invokes this command automatically.

## Prepare only

From the repository root, using approved native Node/npm versions in an isolated,
unprivileged workspace with no production secrets or mounts:

```sh
python3 rethink/native/native_release.py \
  --package-sha256 "$CURRENT_PACKAGE_SHA256" \
  --lock-sha256 "$CURRENT_LOCK_SHA256" \
  --output "$NEW_PRIVATE_BUILD_DIRECTORY"
```

The two hashes must be operator-reviewed hashes of the currently installed
manifests, not values guessed from candidate source. Main is captured once from
`martinemde/rethink`. An active `.github/workflows/ci.yml` and a completed,
successful **push/main** run for that exact full SHA in that same repository are
mandatory. PR checks are insufficient. Missing success blocks before building.
A later main movement does not change the captured source identity. For an
explicit approved sequential release, add `--revision FULL40`: the preparer
requires that exact revision to be an ancestor of the captured main using pinned
GitHub comparison evidence, and still requires successful trusted push/main CI
for that exact revision. The controller rechecks the retained ancestry evidence.
Each release requires a new output directory and a fresh approved target baseline.

The preparer compares manifests before and after local npm install/test/check/
build, then packages dist deterministically. The controller checks all retained
artifact hashes, the preparer identity, captured main and selected CI run again.
Dependency changes block this dist-only flow; there is no install fallback.

A fresh output directory is mandatory. Partial/failed workspaces are evidence,
not resumable releases. `manifest.json` is a preparer success marker, not approval.
`release-journal.jsonl` durably records preparation and deployment outcomes.

## Explicit local deployment

Only after separately reviewed worker/account/firewall enrollment, recorder
baseline approval and native runtime/state compatibility approval:

```sh
python3 rethink/native/native_release.py \
  --package-sha256 "$CURRENT_PACKAGE_SHA256" \
  --lock-sha256 "$CURRENT_LOCK_SHA256" \
  --output "$NEW_PRIVATE_BUILD_DIRECTORY" \
  --deploy-local-target \
  --identity-file "$DEDICATED_CT117_IDENTITY" \
  --known-hosts "$PINNED_CT117_KNOWN_HOSTS" \
  --expected-current "$APPROVED_INSPECT_RESPONSE_JSON"
```

The baseline file must be a freshly inspected, independently reviewed target
identity response. The controller checks its revision, dependency hashes and
recorder switches both before and after building. New inspect baseline hashes
may differ as append-only captures grow; they are never automatically adopted.
The deploy request retains the ORIGINAL approved baseline digest. The worker
compares that saved full private baseline again under the target transaction
lock, requiring identical capture inodes/devices and nondecreasing sizes.
Use only a dedicated forced-command key, never a broad root/Proxmox identity.
The fixed destination is `deploy-rethink@10.0.40.5` (CT117 Local LAN), port 22.
SSH ignores inherited configuration, agent identities and global known_hosts,
requires an explicit host key, disables forwarding and supplies no remote command.
No WAN access is required or opened on CT117. JSON size is capped at 16 MiB.

A transport timeout or failed response means **unknown target outcome**, not
permission to retry. Inspect the retained target transaction journal and current
identities. Never delete its replay records or blindly roll back after candidate
start. The controller intentionally has no retry or replay/resume flag.

## Ready gaps / assumptions

- CI workflow fix PR6 was merged (`262577a`). This does not replace the required
  successful trusted push/main CI run for each exact candidate revision.
- CT120 is not enrolled for native deploy; its current key/firewall only authorize
  the existing CT104 pilot. No new broad credentials were created here.
- Dedicated CT117 forced-command enrollment, source-restricted SSH firewall,
  reviewed baseline/policy and initial release identity must be approved separately.
- Manual native releases of PR4 then PR5 completed on CT117. See
  [deployment result](plain-lxc-deployment-result.md). The observed transport was
  explicit operator Proxmox commands, not this controller’s dedicated SSH path.
- Constants introduced: trusted repository/workflow inherited from preparer;
  CT117 account/address above; 16 MiB request cap; 600-second SSH transaction wait.
  A timeout does not stop the remote transaction and must be treated as unknown.

Offline tests (project environment):

```sh
python3 -m unittest discover -s rethink/native -p 'test_*.py' -v
```
