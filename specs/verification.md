# Migration verification record

Date: 2026-10-21 (America/Los_Angeles).

## Confirmed before publication

- GitHub API: `Runix-lab/runix-fs`, public fork, parent `CurvineIO/curvine`,
  default branch `main`, homepage `https://runixcloud.io/fs`.
- Direct collaborators API returned only `cuihuan` with admin permission.
- Upstream baseline `7d476508e2cd608a1aaaf7837999f52ab633811e`, 1,121 reachable
  commits. LICENSE and preserved upstream English README compare byte for byte.
- Engine source and dependency manifests were unchanged by migration.
- `python scripts/runix/verify_migration.py`: passed.
- `python -m unittest discover -s scripts/runix -p 'test_*.py' -v`: six tests
  passed, including missing/bypassed publisher guards, license replacement,
  lost attribution, lost README and broken development links.
- Independent reviewer mutated all 22 inherited publication jobs to `always()`
  in a temporary fixture; every mutation was rejected.
- All workflow YAML parsed successfully. `git diff --check` passed.
- `RUSTUP_TOOLCHAIN=stable cargo metadata --no-deps --format-version 1`: passed;
  45 workspace packages, 36 default members.
- `RUSTUP_TOOLCHAIN=stable cargo fmt --check`: passed.
- On macOS with installed stable Rust 1.98.0,
  `cargo test --locked -p curvine-fault --features fault-injection`: 19 tests
  passed (17 library, 1 catalog-conflict, 1 process-runtime), none failed or
  ignored. This is a small upstream core-runtime subset.

The first attempt using the named `1.98` channel triggered a local rustup
installation/recovery error before compilation; it was not a failing code test.
The installed stable 1.98.0 toolchain completed the above tests. The dedicated
Linux CI installs the pinned 1.98 channel separately.

## Publication follow-up

The Runix Migration Checks workflow runs the migration checks and the existing
fault-runtime unit subset on Linux. A green result does not establish full
cluster, FUSE, CSI, S3 or commercial readiness. Record the published commit and
actual CI conclusion after push.

Website verification, deployment and publication commits belong to the separate
website repository. The migration introduces no commercial service, production
storage cluster, AWS listing, subscription grant or billing transaction.
