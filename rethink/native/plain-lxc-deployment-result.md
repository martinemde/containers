# Plain LXC deployment result — 2026-11-08

CT117 remains an unprivileged LXC with nesting removed. No OCI runtime is involved.

## Observed releases

1. PR4 squash `313ecdb91ef2abfdb5bee5eadda05a8596342884`: successful push/main CI; local 1,319 tests, type check and build; target transaction completed.
2. PR5 squash `5816e1d76129f0fc18d2745e364fca0914499262`: successful push/main CI; local 1,343 tests, type check and build; target transaction completed.

Order changed from the later requested sequence with explicit operator acceptance. Both deployments used the same reviewed native transaction through the existing operator Proxmox transport, not a newly opened guest SSH listener. After each, actual app process/listener ownership, full candidate dist inventory, local management HTTP200, unchanged config/CA/unit/firewall identities, clean recorder exits and fresh connected markers were verified. Existing capture inodes were preserved and sizes did not decrease. Final application and all three recorder units are active, NRestarts=0; listeners are 10.0.40.5:443/8883 and 127.0.0.1:44401. A subsequent hostname-verified HTTPS request returned HTTP200 using the existing CA. Python 3.13 strict X509 extension enforcement was disabled for that legacy CA only; certificate-chain and hostname verification remained enabled, and certificates were not changed. This proves deployment connectivity, not physical appliance command acceptance.

## Failure fixed

First PR4 attempt stopped cleanly and backed up data, then failed at backup-intent BEFORE dist exchange. The effective unit hash included systemd ExecStart runtime timestamps/PIDs. Hashing the static argv instead fixed this. Old unchanged services were restored and verified. The failed journal and explicit pre-exchange reconciliation remain on target; a fresh baseline/request then deployed successfully. No automatic replay, state restore or downgrade was used.

Each successful transaction retains the old dist and full stopped data archive (including captures, state and CA). Private evidence remains under ~/.local/state/deploy-process/evidence/plain-lxc; no UUIDs, capture contents, certificates or private source are published.

## Deployment operation

Native scripts implement checksummed build/preflight/transaction. Recorder settings are the three `rethink_recorders_enabled` booleans in the targeted beelink recorder playbook. Captures remain on the guest root disk outside application releases. The switch role never recreates the LXC or deletes data.

CT120 automatic native deployment is NOT enrolled. Main CI and publication do not imply an automatic rollout. Dedicated transport enrollment remains separate; the actual observed deployments used explicit operator commands. Existing Podman installation is unused; no runtime uninstall or state deletion was performed.
