# Local engine delivery gate: write/read and crash recovery

Date: 2026-10-26, Asia/Shanghai. Baseline result: **write/read passed;
process-crash recovery failed**. After the configuration repair below,
WAL-enabled master-only, worker-only and simultaneous process-crash recovery
passed. Those original runs were not production, S3, FUSE, HA or Marketplace
tests. A later local MinIO/S3-compatible integration passed below; real AWS S3
and the other release gates remain unverified.
No cloud resources or Marketplace purchases were created for this test.

## Environment and provenance

- Built source identifies itself as `fc52b6e`; no filesystem-engine code was
  modified during these tests. Subsequent commits changed launch preparation.
- Rust 1.98.1, Linux amd64 under Docker Desktop, two CPUs and 6 GiB memory limit.
- Tool image: `ghcr.io/curvineio/curvine-tests@sha256:841254160ea7b619964c5be225e1c5bb5891c1ec91f0d641c2a210db2701cb9d`.
- Debug build, one master and one worker, single Raft member, replica count one.
- Docker `--network none`; loopback only, no published ports, no AWS/S3 access.
- Fresh synthetic-data bind directory, persisted across process restarts. The
  container is removed after the test; the bind directory remains for inspection.
- Runtime payloads, DB files and logs are excluded from Git.

Binary SHA-256:

| Binary | SHA-256 |
| --- | --- |
| curvine-server | `0368937e2dfba056045926c9f8fa4c9b228b1170efeea579d40c9cd5fe179df9` |
| curvine-cli | `f1f517005f18b5157c017d1759b0c5448a1efac9da3babc12a1f5b9f3f50dd12` |
| curvine-fuse (compiled, not mounted) | `97ac179bbbed6db6d5054bb304014a85c5039758de158f5cde734bf6cffb3c67` |

## Reproduce

The script is an integration test, not a provisioner or readiness stub. It
requires the existing build volume and tool image. Use a new, empty local
directory every run. It kills only the two child engine processes it started.
No existing cluster is contacted. Run from the repository root:

```sh
smoke_dir="$(mktemp -d /tmp/runix-engine-smoke.XXXXXX)"
docker run --rm --name runix-fs-marketplace-smoke \
  --platform linux/amd64 --network none --cpus 2 --memory 6g \
  --mount type=volume,source=runix-fs-marketplace-target,target=/build,readonly \
  --mount type=bind,source="$smoke_dir",target=/smoke \
  --mount type=bind,source="$PWD/scripts/runix/local_engine_smoke.sh",target=/run-smoke.sh,readonly \
  ghcr.io/curvineio/curvine-tests@sha256:841254160ea7b619964c5be225e1c5bb5891c1ec91f0d641c2a210db2701cb9d \
  bash /run-smoke.sh
```

The original failing baseline script (commit 5d3d3b9) SHA-256 is
`150e9d43cd92281f290136efcb83da2e7530f52cdb67fcc8651edb86fbc7cbb7`.
It waits for a master report with available worker capacity before writing,
uploads 4 MiB, downloads and byte-compares, sends SIGKILL to master and worker,
restarts them without formatting, and retries the download and comparison.
An error or mismatch fails the script; a CLI success message alone is not proof.

## Observations

1. The image supplies `CURVINE_MASTER_HOSTNAME=localhost`, which initially
   conflicted with explicit 127.0.0.1 journal membership. The runner now sets
   explicit matching master/worker/client hostnames. This was a test setup
   correction, not an engine fix.
2. Metadata readiness alone was insufficient: the first write attempt ran
   before worker registration. CLI emitted a write error and produced an empty
   download; byte comparison correctly rejected it. Wait for worker capacity.
3. With worker readiness fixed, upload and download both reported 4,194,304
   bytes and `cmp` succeeded. Payload SHA-256:
   `5e06224c326ae23f75f8d34ad284f47c8adeb6f6fb3fa1d6110902cf1e72183d`.
4. Following immediate simultaneous process kills and restart, all 40 recovery
   attempts failed to retrieve the file. Master reported `FileNotFound` and
   later reported a worker block with a missing inode. The runner exited 1.
   Raw local evidence: `/tmp/runix-marketplace-local-smoke-20261026b/`.
5. A separate experiment requested `[master.rocksdb] disable_wal=false` in
   the TOML. The parsed configuration reflected false, but the actual opened
   metadata DB still logged `disable_wal: true`. The same recovery failure
   occurred. Evidence: `/tmp/runix-marketplace-local-smoke-20261026-wal/`.
   This is not a successful WAL-enabled test. The ineffective parameter was not
   added to the committed runner as if it offered durability protection.

## Source findings and next repair scope

`curvine-master/src/master/meta/store/rocks_inode_store.rs` forces
`.set_disable_wal(true)` in its constructor regardless of the requested flag.
`journal_writer.rs` enqueues metadata entries, while `sender_task.rs` flushes
them asynchronously to Raft. These observations identify relevant durability
boundaries; they are not a complete proof of why every recovery path fails.

Before a production fix: add a deterministic engine regression proving the
acknowledged create/write/complete operation survives process death, inspect
the durable Raft proposal/commit/replay boundary, respect any intended metadata
WAL policy, and verify replay idempotency and checkpoint consistency. Cover
master-only, worker-only and simultaneous failures plus three-master failover.
Do not mask loss by sleeping before the kill, force-formatting or returning
successful provisioning. Do not change upstream storage semantics without
matching specs, modification notice, unit tests and runtime regression results.

## Configuration repair and verified reruns

RocksInodeStore now preserves DBConf.disable_wal. The default MasterConf policy
is unchanged; the smoke runner explicitly enables metadata WAL. It also rejects
nonempty test directories and accepts only both/master/worker crash targets.
This does not repair the asynchronous Raft acknowledgement boundary or establish
multi-master consistency. Do not interpret a local WAL as quorum replication.

All six inode-store unit tests passed, including both WAL policies, recovery of
an acknowledged local DB write after a child exits without Rust destructors,
and the three existing iterator/corrupt-SST tests. The child really executed
one test; an initial helper-name error caused zero child tests and a parent
failure, and was corrected before the passing run.

The actual rebuilt server passed three isolated 4 MiB CLI write/read/crash/
restart comparisons with no delay added before the kill:

| Crash target | Payload and recovered SHA-256 | Local evidence directory |
| --- | --- | --- |
| Master and Worker | `2b71e13bba34ded99a361b09de16ec3e72ab6d69028e9d403bbe7cd359d02353` | `/tmp/runix-fs-wal-both.rc4Nx7/` |
| Master only | `7799b824ebf7153d2c30fa027969d2ff8bcf6a0cb62e5d2ebac9499336a3066c` | `/tmp/runix-fs-wal-master.0gv1nP/` |
| Worker only | `c1f1670e181b2f6b80a70b592559ae7d9a45b691606d21b47da803d2f6b2aa52` | `/tmp/runix-fs-wal-worker.2uLAa1/` |

For individual targets, set RUNIX_SMOKE_CRASH_TARGET=master or worker in the
container environment. Use a fresh evidence directory for every run. The above
baseline binary hashes are historical, not the rebuilt server hash.

FS release still requires S3 persistence/recovery, FUSE, three-master failover,
backup/restore and the unbuilt commercial registration, organization
authorization, PAYG lifecycle and usage pipeline. No power-loss, RPO or SLA
claim follows from process-kill tests.

## Local S3 compatibility gate

Use a newly created internal Docker network, a temporary MinIO container from
the already installed official image digest, and the rebuilt engine. Publish
no ports and use no existing buckets/volumes/customer data. Use independent
boto3 calls against the temporary object store to seed a 4 MiB object and check
write-through output. Verify cache-mode read, read-write upload, and retrieval
after simultaneous master/worker SIGKILL/restart without formatting. Check all
payloads byte for byte. Temporary credentials are fixture-only, stored outside
Git, and never printed. Cleanup only containers/network created by this test.

This is an S3-compatible local integration, not AWS S3, account isolation,
fs_mode asynchronous persistence, FUSE, HA, backup/restore or public delivery.
Record actual outcomes and source/binary hashes after execution; do not count
the plan or a running container as a passing test.

### Actual result, 2026-10-27

**Passed**, using the real compiled engine and independent boto3 object-store
calls, not a mocked file service:

1. SDK created a new local synthetic bucket and 4,194,304-byte source object.
2. CLI mounted the bucket in `cache_mode`, `read_write`, with UFS verification,
   read the object and compared every byte to the independent source.
3. CLI uploaded a separate 4,194,304-byte object through the mount.
4. Immediately SIGKILLed Master and Worker, restarted both without formatting,
   and downloaded both source/upload paths. Each matched its original bytes.
5. An independent SDK GetObject read the uploaded object directly from MinIO
   and matched it against the original upload, proving actual write-through.
6. Docker inspection during the test confirmed network Internal=true and both
   engine/store HostConfig.PortBindings={}. After completion, container and
   network inventories showed no remaining runix-s3-smoke resources. Existing
   unrelated containers were not stopped. No AWS resource or bill was created.

Payload evidence:

| Payload group | Bytes per file | SHA-256 |
| --- | --- | --- |
| Seed, read-before, read-after | 4,194,304 | `7bda1bd794a4a828876af8f1935d4bdf25a337e89a4a6a3535b0bc16c0468f7c` |
| Upload, direct-S3-read, upload-after | 4,194,304 | `b485e7aace49941bcdbc469cc8f1dc3a222dcc6aa5c9f00c469192601ca8afd4` |

Actual server SHA-256:
`707497ccfd450d5c7f6c252230819d0c4a9297328d74207b44f2bc2f4c640914`.
CLI SHA-256:
`f1f517005f18b5157c017d1759b0c5448a1efac9da3babc12a1f5b9f3f50dd12`.
This reuses the earlier WAL-repaired build; it is not a rebuild of the latest
documentation/outbox commit. Engine behavior was not changed during this run.

Local raw evidence directory (not committed):
`/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-s3-smoke-m715epnl/`.
It contains payloads, evidence.json, binary-hashes.txt and private logs; do not
upload mount configuration or logs containing even fixture credentials.

The first attempt failed before storage operations because the tool image's
Python could not load the current SDK. The fixture now runs in a separate
official Python container. The second failed at CLI argument validation:
`--read-verify-ufs` is a boolean flag in this build and must not be followed by
`true`. Both failures were retained and their resources cleaned; neither was
counted as storage success. The third run passed all steps above.

Reproduce with already installed images/build volume and the existing SDK:

```sh
/tmp/runix-marketplace-venv/bin/python scripts/runix/local_s3_smoke.py \
  --sdk-dir /tmp/runix-marketplace-venv/lib/python3.11/site-packages
```

The host orchestrator does not pull images or install packages. The separate
fixture requires Python >=3.10. SDK dependencies are mounted read-only.

- MinIO image: `minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e`.
- SDK image, downloaded from official Docker Hub library/python:
  `python@sha256:5b8b1421ccb6a525860a77863c049eab5847076cda34e030c75a80c58faf3f3c`.
- Engine tool image remains the earlier pinned Curvine CI digest.

Two additional fault tests verify failed Docker starts/engine runs clean up only
their unique invocation resources, delete the temporary credential file and
preserve unrelated service/network names. Combined Python suite: 61 passed.
Shell syntax, Python compilation and provenance checks also pass. These do not
replace the real integration run or prove AWS account-level tenant isolation.

## Two-boundary local verification contract, 2026-10-29

Add a repeatable local-only runner using the already cached immutable images and
read-only engine build volume. Create two new internal Docker networks, each
with an independent synthetic object store, private credentials, evidence
folder and engine state. Reuse the existing actual CLI write/read/SIGKILL/restart
script for each boundary. Both stores must be running and independently seeded
before network probes. Verify own-store access succeeds, peer store IP access
fails in both directions, and the peer's valid credentials cannot read objects
from the local store even when the network path is reachable. Compare hashes to
prove identical object paths contain different independent payloads.

No host ports, image pulls, host Docker socket inside containers, shared engine
state, cloud credentials, AWS calls or customer data. Run engines sequentially
to bound local memory; stores coexist for isolation probes. Use unique invocation
resource names, 0700 runtime folders, 0600 temporary credential files, bounded
subprocess timeouts, and cleanup in failure paths. Verify owned resources are
gone using successful fresh Docker inventory commands; cleanup errors must fail
the test instead of printing success. Preserve unrelated resources and retain
only local synthetic payloads/private logs, never commit runtime state/secrets.

Unit tests must cover Docker start, engine/probe failure, cleanup failure and
scoped removal. A real integration run must separately record actual hashes,
results and cleanup. This is evidence about Docker deployment boundaries only:
not AWS IAM/VPC isolation, shared-cluster authorization, quotas, FUSE, SSO,
Marketplace activation or a production service. No public launch follows.

### Actual two-boundary result, 2026-10-29

**Passed twice locally**, with the final run using a separate peer-credential
probe file: peer credentials never enter the engine or object-store environment.
Both stores were alive and independently seeded before probing; each engine ran
sequentially in its own boundary. Each passed actual S3-compatible read,
write-through, simultaneous master/worker SIGKILL, restart without formatting,
byte comparisons and an independent SDK read of its uploaded object. Own-store
positive controls passed; peer-IP TCP connections failed in both directions;
using the other store's credentials against the reachable local endpoint returned
an explicit 403 authorization error. Same bucket/key names contained independent
random payloads. This is not a shared service or an organization-authz test.

Final run payloads (4,194,304 bytes each):

| Boundary | Seed/read-before/read-after SHA-256 | Upload/direct-S3/recovered SHA-256 |
| --- | --- | --- |
| A | `b89af1cae4ff67675c8c2f6d2ddd3a41a104378952495772e48b1c05cd8b44be` | `5c196d7ce8e644bedafed6b085aa78c3bdba284ce63ebc97cdd549d20d5478ac` |
| B | `5c5a551db3ae2cc2c5b0c9044a1d45b7b959bba61cd1b526a1821f95e7d46d2f` | `a87011429f559da9ac13a6044fd20a662fc924b579798c3269dc43ea449cc540` |

Both used the previously WAL-repaired server hash
`707497ccfd450d5c7f6c252230819d0c4a9297328d74207b44f2bc2f4c640914`
and CLI hash
`f1f517005f18b5157c017d1759b0c5448a1efac9da3babc12a1f5b9f3f50dd12`.
No engine source changed or rebuilt during this step. These are not fresh
release artifacts for the latest control-plane commit.

Actual running-engine inspection confirmed no peer-credential environment,
HostConfig.PortBindings={}, Privileged=false and read-only /build volume.
Successful post-test Docker inventories independently confirmed zero remaining
runix-tenant-smoke containers or networks. Both temporary credential/probe files
were gone. Existing unrelated services were preserved. No AWS resource, public
listener, Marketplace subscription or metering request was created.

Final private evidence (not committed):
`/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-tenant-smoke-0hmv2kzn/`.
Initial passing run before separating peer credentials:
`/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-tenant-smoke-_d8f6niu/`.
Payloads, raw logs and test mount configuration remain private synthetic runtime
state. Temporary credentials are inert after store removal, never AWS secrets.

Reproduce with the existing SDK environment and cached images:

```sh
/tmp/runix-marketplace-verify-20261028/bin/python scripts/runix/local_tenant_smoke.py \
  --sdk-dir /private/tmp/runix-marketplace-verify-20261028/lib/python3.14/site-packages
```

Final runner SHA-256:
`7c7fa5ef90745fea741f85598afbe0550f739828fdda72118b8faca349253db7`;
probe SHA-256:
`91077e71e5e1d9e11e18277c60fde6ea80878a82e007a0d7e85b8bf6b82f63f7`.
Ten new unit tests cover orchestration cleanup failures, resource scoping,
credential handoff, positive/negative controls and rejection of infrastructure
errors as authorization proof. Combined Python suite: **178 passed locally**.
A test-only mock response iterator initially exhausted across subcases; reset
per subcase and rerun successfully. No runtime integration failure was hidden.

This does not establish AWS VPC/IAM isolation, production organization access,
license activation, hard quotas, FUSE, HA, restore-from-backup, public login or
Marketplace buyer delivery. Those remain required release gates.
