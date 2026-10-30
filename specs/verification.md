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


2026-10-30 journal acknowledgement repair candidate implemented: separate commit
request channel; drain/force-flush of prior queued entries through real Raft
commit/apply acknowledgement; no success on timeout/disconnection/failure;
namespace guard released while waiting. Synchronous mutation RPC dispatch,
batches and retry-cache successes all pass the same fence then recheck leader
state. Existing serialized journal/protobuf formats and default WAL policy
remain unchanged. Known reads/reconstructible reports are exempt; async job
acceptance/HA are not newly claimed durable.

All203 active curvine-master lib unit tests passed,0failed,1existing ignored
large-tree benchmark. All12 new fence/order/concurrency/error/guard/RPC tests
passed. rustfmt, migration/provenance and whitespace checks passed; captured
source hashes match current candidate. Initial test launcher mount failures and
readonly ../target/testing failures were fixed only in the private fixture.
No test assertion was weakened. Test logs and runtime databases stay outside Git.
Real newly compiled image recovery and long-batch failure-injection replay are
still pending; no production resource, Marketplace purchase or public launch.


First passing source-pinned local image gate, 2026-10-30:

- Source811149c0a7d970832c2a4638a51fcec4f420fc55, tree5fb2640304f3252e1385e26b05909dc18a149a59;
  actual locked/offline native build completed in1m10s; compiler rustc1.98.1.
- Actual retained local image ID
  sha256:1196eb04dbcce2c021feec1bbe01196eea52fbfb97c73a0fee9631748f037237.
  This is a Docker-local artifact, not a published registry/release reference.
- Both in-image components reported811149c/protocol1. Actual binary SHA-256
  matched fresh captured inputs; mounted-harness digest matched before/after.
- UID1000, no network/ports or build-cache mount, read-only root, dropped
  capabilities/no-new-privileges and a fresh owned data volume were verified.
  4194304-byte write/read and simultaneous master/worker SIGKILL restart passed;
  payload and both downloads hashed
  5a349726db33913ba6344888fcd4a1fe4ebaf7ffeed78ef6632f31ed1d4e141f.
- Passing artifact.json was issued after owned container/volume cleanup, with
  production_release=false and bit_reproducibility_verified=false. Runtime
  evidence remains private/outside Git. No cluster port was made public.

GitHub Actions41033344673 succeeded for811149c:
https://github.com/Runix-lab/runix-fs/actions/runs/41033344673
Native203-pass unit verification is separate from that CI status. Follow-up
same-image long-batch failure injection and individual master/worker/repeated
both-process crash cases have started but have no final result yet. This passing
local artifact does not establish FUSE/S3 image compatibility, HA, hard quota,
production provisioning, billing or Marketplace buyer/public availability.
No AWS resource, purchase or public listing/deployment change occurred.


Completed same-image crash matrix, 2026-10-30. The verified source811149c
local image was used without a build-cache mount in four further UID1000,
no-network/read-only-root/capability-dropped fresh-volume cases:

| Case | Actual recovered4MiB SHA-256 |
| --- | --- |
| long-batch-both | fada4e92d24bb25d41c373738552a4396373b9f12667fbb04a800b888c4d64b8 |
| default-master | 9239387d85a02b65a7e69b6b9dde977f3410ff4e468c7d043034f21a009f58da |
| default-worker | 16daded3c9e8a8589072be102547c80880e79d7601f9ee9fd27457bf29b54e69 |
| default-both-repeat | 33edfe43edb82035dd298f6777956740b949d5109d0e47c9d2fee772b97c8fa4 |

Each case verified in-image binary/version identity and mounted-script hash,
compared real payload/before/after bytes and confirmed owned container/volume
cleanup. Including the original artifact gate, five real image crash runs passed.
The60000ms writer batching injection previously failed on8a0d213 with committed
Raft index1 and FileNotFound; repaired811149c recovered successfully from committed
index5 in that profile. This is evidence for the acknowledged-write window
repair, not proof that all possible historical/default failures have one cause.

The first matrix launcher used an unresolved /var path and was rejected by the
strict mount-source check, with no passing result. Resolving its private script
to /private/var produced the expected /host_mnt/private/var mapping and passed
the existing check; no validator or engine assertion was weakened. Container
configuration and synthetic engine evidence were retained outside Git. No
unrelated Docker resource or verified local image was removed.

The local image remains production_release=false: FUSE/S3 image compatibility,
physical/tenant hard quota, backups/restore under this image, production identity,
provisioning, licensing/metering transport and buyer/public tests remain separate
gates. Existing seller/product evidence is historical Staging; this increment
made no AWS call, paid resource, purchase, publication request or public deployment.
The latest explicit scope remains local and draft; no persistent budget approved.


## Verified pinned-image offline restore, 2026-10-30

Passed using source811149c0a7d970832c2a4638a51fcec4f420fc55 and the same
local image sha256:1196eb04dbcce2c021feec1bbe01196eea52fbfb97c73a0fee9631748f037237
for both original and restored engines. Both actual executions verified UID1000,
read-only root, dropped capabilities/no-new-privileges, actual in-image hashes/
versions and a read-only script digest. Neither engine mounted the build cache,
source tree or the original runtime folder. Each used a fresh owned volume;
only a separate no-network preparation container normalized volume ownership.

The original engine was actually stopped before copying its metadata/journal/
worker state. Original engine/store/client/network removal was verified before
creating the restore environment. Objects were exported/imported through the
existing bounded two-object integrity manifest and independently read back.
The restored engine read both old files and wrote a new file; independent SDK
readback from the fresh object store matched the new write.

| Actual4MiB group | SHA-256 |
| --- | --- |
| Original/source/import/restored read | 519503bed6c55c97c6151384eee74eecea41493b9b4b1b8aa8d99a54ffff8669 |
| Original/upload/import/restored read | 840ec8d0c67c35e5ddab9c2bf580916f0282a3f138ef040f937ccc37b8258a7d |
| New post-restore write/read/direct S3-compatible read | 0ee734caec6724440c021ef0d20ea07dcf3b739c6f261a58a136e00dbee44743 |

All seven actual host payload files were rehashed after completion and matched
the fixture's evidence. Fresh Docker inventories independently confirmed both
environments' owned engine/preparation/store/client containers, volumes and
networks removed. The private fixture environment file was gone. Raw databases,
credentials and runtime evidence stay outside Git; no AWS resource or purchase.
This retains worker state and remains an offline local synthetic recovery point,
not cold-cache recovery, online/scheduled/encrypted production backup or an
approved retention/RPO/RTO policy. No SaaS readiness/publication is implied.

The runners accept --engine-artifact followed by the passing artifact.json path
and the existing --sdk-dir. Source619f584f779d33e637b206d463f069f71d57daf7 was pushed;
CI41044325525 succeeded:
https://github.com/Runix-lab/runix-fs/actions/runs/41044325525
All366 Python tests (including9 new image-fixture tests), shell syntax,
migration/provenance and whitespace checks passed locally. The engine's earlier
203 active Rust unit tests and five actual crash runs remain separate evidence.
