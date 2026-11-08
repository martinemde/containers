# Plain-LXC immutable main pipeline

## Prepared path

1. The CI-only main push trigger fix was merged. This native dist-only path
   supersedes OCI deployment for this plain-LXC target; image publication remains
   separate and does not deploy anything.
2. Wait for trusted `ci.yml` push/main CI to succeed. On the controller run
   `prepare-pr5-native.py` with approved current package/lock hashes and a new
   private output directory. It captures main once, validates CI for that exact
   SHA, downloads immutable source, tests/checks/builds natively, and hashes the
   source archive, dist archive and dist files. Later main movement is allowed.
3. Review `manifest.json` and CI evidence. Bind full commit plus manifest,
   source and dist SHA256 to the controller's target request. Neither a PR number
   nor an OCI tag/runtime is part of release selection.
4. Pass only this verified bundle and explicit expected-current baseline to the
   reviewed CT120 updater after maintenance authorization. The target must never
   resolve main, run npm, fetch dependencies, or build application source.

### Explicit ordered historical releases

Optional preparer/controller `--revision <full SHA>` selects an ancestor of
captured main. GitHub compare evidence must prove ancestry; trusted ci.yml
successful push/main CI must exist for that exact SHA. This supports building
PR4's merge first, then PR5's merge, even after both have merged, without
rewinding main. `main-ancestry.json` is hashed evidence; `main.json` records the
captured main tip, not necessarily the selected commit. Default remains main.

## CT120 integration contract

The preparer only builds; it does not deploy. Controller and target updater are
separate work products. The controller should verify artifact hashes immediately
before transfer and record request, updater and inventory identities. Native Node
must satisfy the package engines; the installed production tree must match the
approved unchanged package/lock and installed-version baseline before stopping.
The historical package/lock hashes from CT117 are useful comparisons, not a CT120
baseline. CT120 needs a fresh read-only baseline and explicit operator approval.

The target transaction must preserve config, CA/cert/key, persistent state,
dependencies, bridge policy, app unit, guest settings and network controls.
Preflight must pin exact current release/artifact/config/unit identities. Stage
checksum-verified dist on the same filesystem and retain old code. Preserve
recorder definitions, persistence and enabled states for washer/dryer/sidekick:
only originally enabled recorders may restart; disabled means disabled. Preserve
append paths/inodes and nondecreasing capture sizes. Require fresh connected
markers for restored enabled recorders without adding an observer or printing
secret argv. Resolve persistent/transient definitions from current CT120 evidence,
not from the old helper's all-three transient-unit assumptions.

Stop app/recorders in the reviewed safe sequence and take a stopped consistent
state backup before switching. Prove exact full release identity, management/MQTT
health, recorder restoration and unchanged config/CA/firewall/HA identities after
start. Connectivity alone does not prove fresh appliance state. No automatic
rollback after candidate start or state/capture rewind; use an explicitly reviewed
coordinated recovery procedure. No appliance commands or HA/MQTT reloads.

## Remaining review/authorization

The old `rethink-update.py` is not suitable as-is: online dependency-upgrade paths,
fixed historical identities and transient/all-three-recorder assumptions must not
be reused. The included `native_target.py` and tests implement the native dist-only
transaction. A fresh reviewed CT120 baseline and explicit enrollment remain
necessary before deploying there. Code existence alone is not authorization. No target
transaction is implemented by the artifact preparer.

## Validation and assumptions

All 47 offline native tests pass, including CI identity rejection, immutable
source capture, artifact verification and target transaction safety. Manual CT117
releases of PR4 then PR5 completed; see [deployment result](plain-lxc-deployment-result.md).
CT120 automatic deployment is not enrolled.
Assumed repository `martinemde/rethink`, main branch, trusted active ci.yml, native
supported Node/npm and unchanged version writer. PR5-only identity was removed.
No application changes, OCI runtime, provisioning or production constants changed.
