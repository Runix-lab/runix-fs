# Local engine delivery gate: write/read and crash recovery

Date: 2026-10-26, Asia/Shanghai. Baseline result: **write/read passed;
process-crash recovery failed**. After the configuration repair below,
WAL-enabled master-only, worker-only and simultaneous process-crash recovery
passed. This is not a production, S3, FUSE, HA or Marketplace test.
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
