# Collector build migration gates

Inspection date: 2026-11-08. These are applications built locally for a declared
personal-data guest, not third-party image wrappers. Their build recipes belong
in this repository once reviewed source can be fetched at an immutable public
revision. Their runtime units, private inputs, identities and secrets do not.
No source code or private data was copied here and no running guest was changed.

| Image | Current recipe | Verified blocker |
| --- | --- | --- |
| `eight-sleep` | `sleep-data/Containerfile`: Python 3.13 slim, install stdlib-only `sleep-data` package with Hatchling | `project.md` says `repo: null`; GitHub `martinemde/sleep-data` returns 404. No verifiable published source commit. Python base is not yet digest-pinned. |
| `accounting` | `accounting/Containerfile`: Debian bookworm slim, Python and hledger 1.52; release checksum already present; allowlist `bin/daily.py`, `bin/rebuild`, `bin/ynab-prepare` | GitHub repository is private. Its verified HEAD `67b3557bfc97780f8f082e9580791f532aba2ab8` contains only README.md. Local Containerfile and daily collector are untracked. No deployed-code source pin. Debian base needs a verified digest. |
| `claude-history` | Role allowlists `archive.py`, `semantic.py`, `deploy/import_snapshot.py`, `deploy/Containerfile` from external `~/src/martinemde/claude-data` | Expected source directory is absent. GitHub `martinemde/claude-data` returns 404. Recipe and dependency requirements cannot be verified. |

A 404 means unavailable to this authenticated lookup, not proof a repository can
never exist. `localhost/*:managed` is a local build tag, not an immutable source
or image pin. Do not substitute an unrelated similarly named project.

## Before adding each image to the publication matrix

1. Publish an explicitly reviewed code-only source repository, or decide on a
   separate private build pipeline. Do not make existing private financial/health
   repositories public just to enable CI. Never add private Git credentials to
   a public Containerfile or unauthenticated pull-request build.
2. Verify an exact source commit contains the deployed build allowlist and lock
   metadata. Pin the download and verify its checksum. Keep a deny-all context;
   never recursively copy working trees, README contents, exports or data.
3. Verify first-party/official base publisher ownership, keep the upstream tag,
   and pin its actual registry digest. Verify any downloaded release checksum.
4. Add `Containerfile` and a per-image `test.sh` that runs synthetic/offline CLI
   and import tests with `--network none`, no credentials and no mounted data.
5. Add the image to the existing matrix only when build and smoke tests pass.
   Publication is not deployment; do not change live runtime units or mutable
   `localhost` consumers until a separate accepted immutable-digest migration.

This records a deliberate blocked migration, rather than publishing fabricated
build recipes or treating an unrelated wrapper as a collector replacement.
