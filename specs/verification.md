# Migration verification record

## Marketplace preparation branch, 2026-10-28

New HTTP/auth code snapshot `0d5189c1f9f413f947803e6ca97da8fceead06ec`
passed [run 40624083374](https://github.com/Runix-lab/runix-fs/actions/runs/40624083374).
Actual logs show 153 Python tests and the 19 Linux fault-runtime tests passed.
The Python suite includes real temporary loopback HTTP requests and ephemeral
RSA signatures, with Marketplace API responses supplied by botocore Stubber.
This does not prove a real IdP, AWS purchase, license activation, deployed
HTTPS endpoint or cluster delivery. No public SaaS URL is established.

Published source review branch: `codex/marketplace-saas-integration` in
Runix-lab/runix-fs; remote main remains separate. Preserved the remote Chinese
quick-learn update fbe0557 while merging into the preparation branch.

GitHub Actions [run 40620464111](https://github.com/Runix-lab/runix-fs/actions/runs/40620464111)
completed with success for exact commit
`d7c57e8c043f258a1b0a77d87a53e15ba5b229f8`. Job details and downloaded logs
confirmed 118 Python tests, provenance/whitespace checks and 19 existing Linux
fault-runtime tests passed. This is not a full-engine build, inode-store WAL
test run, FUSE/S3 integration or commercial delivery test. Separate local engine
and S3-compatible observations remain in marketplace-local-smoke.md.

The branch includes local registration/binding, exact storage interval accounting,
durable metering and negative-event guards with their explicit unimplemented
authentication, activation, collector, provisioner and production boundaries.
No live Marketplace purchase, final-metering acceptance, public visibility or
operational SaaS URL is established by GitHub CI.

## 2026-10-29 local OIDC protocol and regression evidence

New internal code/PKCE foundation and separate pinned ID-token verifier pass
30 new tests; the complete Python suite is **283 passed**. Provenance, Python
compilation and whitespace checks pass. Existing access-token rules remain
unchanged and ID tokens still cannot authenticate API bearer requests.

A fresh cached official Casdoor instance issued a synthetic authorization code,
enforced S256, and returned a real signed ID token verified with its actual
4096-bit RSA public key. Fresh-code/wrong-verifier, consumed callback and
redeemed-code/original-verifier cases were refused. Owned Docker resources and
secret environment file were removed and the inventories checked. See
[OIDC login foundation](control-plane-oidc.md) for evidence and limitations.
This does not establish browser-session safety, production SSO, public TLS,
shared Router identity, tenant provisioning or a live Marketplace purchase.

Implementation `7088fac577b3723077added3f7d6357439023ff4` passed GitHub Actions
[run 40824991106](https://github.com/Runix-lab/runix-fs/actions/runs/40824991106):
actual completed success for both migration and Linux fault-runtime subset jobs.
The real local IdP protocol smoke is separate from CI's unit/source checks.

## 2026-10-29 browser account and session evidence

Added the optional browser account wrapper, durable session/CSRF handling,
metadata-only personal organizations and registration-cookie binding. **329
Python tests pass locally**, including 46 new tests in this increment. Real
RSA verification, actual loopback TCP/WSGI request cycles, transaction/crash/
replay/race checks and original-logo visual rendering are verified locally.
The real Casdoor protocol smoke also passed again with all owned resources
removed. See [Browser account](control-plane-browser.md) for precise fixture
boundaries, screenshot/evidence locations and the remaining production gates.
No actual browser/production IdP login, paid buyer purchase, public service,
cloud deployment or Marketplace publication is established by these checks.

Browser implementation `bda58303cc7ffe032f1c8f156bd39a4aa7a16c86` passed GitHub
Actions [run 40995361989](https://github.com/Runix-lab/runix-fs/actions/runs/40995361989):
actual completed success for migration and Linux fault-runtime subset jobs.
No production deployment or public SaaS verification occurs in this CI.

## Original migration evidence

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
The named toolchain was subsequently repaired to 1.98.1 and completed the same
19 tests successfully; installed stable 1.98.0 passed them independently.

## Publication follow-up

The Runix Migration Checks workflow runs the migration checks and the existing
fault-runtime unit subset on Linux. A green result does not establish full
cluster, FUSE, CSI, S3 or commercial readiness. Record the published commit and
actual CI conclusion after push.

Initial published migration commit: `6476faec3e08eaf776c2a2a0d994c74d056a6a45`.
Linux CI run `39718596322` passed all 19 fault-runtime tests and all six migration
tests. Its whitespace step flagged the original upstream README's line 9 trailing
space. Preserve this archived document byte for byte and exclude only that file
from whitespace checks; the provenance verifier still rejects any byte change.
The first run's overall conclusion was failure, not a fully green migration.

Follow-up commit `7e11b8889882cc7375602565e91b5afb07e4372b` fixed only the archive
whitespace policy and recorded the result. Linux run `39718783390` completed
with **success**: both migration and fault-runtime smoke jobs passed. Independent
review confirmed ordinary README whitespace errors remain rejected while any
archive byte change remains rejected by provenance checks.

The main website's `/fs` and `/docs/fs` were independently fetched after
publication: both linked to `Runix-lab/runix-fs`, product attribution still linked
to Curvine, and the docs displayed master 9001 / worker 9002. The site deployment
was explicitly approved by the owner before publication. Product-mirror
deployment evidence belongs to the website repository's publishing record.

Website verification, deployment and publication commits belong to the separate
website repository. The migration introduces no commercial service, production
storage cluster, AWS listing, subscription grant or billing transaction.
