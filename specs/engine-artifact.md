# Pinned local engine artifact and real runtime gate

Contract, 2026-10-30. Build a self-contained Linux amd64 engine image for the
future dedicated provisioner. Marketplace delivery remains SaaS Subscription;
this internal image is not a new AMI/container Marketplace product or a release.
No cloud resources, registry push, customer data or public listener is created.

Capture one full Git commit, clone its complete tracked source into a fresh
private directory and detach that exact commit. Do not copy dirty workspace
files, credentials, local runtime data or a .git alternates dependency. Build
with the already installed immutable Curvine tools image, cached Rust 1.98 and
locked offline Cargo dependencies. Source is read-only at /workspace; target
and Cargo/Rust caches are task-owned existing volumes. Refuse a concurrent
container using these caches before starting; never remove the caches. The
binary build must actually finish, not just find an older output in the volume.

Record the source SHA/tree, Cargo.lock digest, actual compiler version, builder
image digest, architecture and resulting binary SHA-256. Pin source Git access
only to that known snapshot; do not use wildcard safe.directory. Runtime Git
version metadata must identify the captured source, with no invented tag/SHA.
A successful single build is not proof of bit-for-bit reproducibility.

Build a unique local image from the pinned cached tools base and freshly copied
curvine-server/curvine-cli binaries. Keep internal names, Apache LICENSE, NOTICE
and upstream provenance. This initial runtime retains the tools base's native
libraries and license materials; it is not claimed to be a minimal/hardened
production image, complete SBOM or signed public release. No source credentials,
SDK keys, database, runtime logs, cargo cache or .git goes in new image layers.
Use a non-root runtime user, explicit binary paths and a harmless help default.
Record the immutable local image ID; never infer registry availability.

Adapt the existing engine smoke to an operator-selected absolute binary
directory, retaining its old default. Run actual master/worker and CLI from the
new image with no build-volume mount, no network and no published ports. Use a
fresh owned data volume, drop capabilities/no-new-privileges, verify runtime
UID and container configuration, and byte-compare 4 MiB write/read plus actual
SIGKILL/restart recovery. Export only synthetic evidence to the private runtime
directory. Remove only owned build/smoke containers and smoke volume; preserve
images as local artifacts and existing build caches. Failure must not produce
a passing artifact receipt; unknown cleanup must be reported as failure.

Unit tests: source/config validation, digest/architecture/identity verification,
command construction, missing/mismatched files, image pinning/labels, denied
unsafe runtime settings, failed build and scoped cleanup. Actual Docker smoke
is a separate gate. No endpoint or provisioner returns fabricated success.

Production gates still include image minimization/security review, source and
OS dependency SBOM/license review, reproducible release build/signing, FUSE,
S3-compatible image validation, hard quota, operational provisioning/revocation,
production budget, real SaaS identity/licensing/buyer tests and public review.

Implementation: scripts/runix/engine_artifact.py. Its CLI requires an absolute
repository path and a full existing source commit. No branch name/HEAD is
accepted as the build reference. Source checkout disables only checkout hooks
in that independent snapshot, not repository commit/review hooks. It does not
change the user's Git configuration. BUILD_VERSION overrides are cleared so
binary version metadata must identify the actual captured Git source.

Creation responses can be lost after Docker has created a resource. Each
operation uses a unique label; ownership is adopted by actual inspection before
scoped cleanup. A foreign builder or active cache user stops the operation.
Image IDs are taken from actual local inspection and cross-checked against the
build output reference. This does not invent a registry digest. A passing
artifact.json is written only after actual data comparisons and cleanup.

Primary Docker references checked 2026-10-30:

- https://docs.docker.com/reference/dockerfile/
- https://docs.docker.com/engine/containers/run/

Initial implementation verification: 19 new unit tests cover source, compiler,
ELF architecture/executable validation, immutable image configuration, runtime
boundary, ownership, failed/lost creation responses and cleanup. Actual pipeline
verification is separate; a running build or unit suite is not a passing image.

First actual pipeline attempt completed the real locked/offline Cargo build in
22m25s from d7051cff82e12e73fe469cf7cb8ba34b98a536e1. It then stopped before
image creation: the initial adapter incorrectly expected CLI's human --version
to contain a commit. Actual source inspection and execution established that
both components already expose --version-json with component/git_commit and
protocol fields. The server human version included d7051cf; the CLI human
version contained only its package version. No CLI/Rust behavior was changed.

The adapter now validates the existing bounded structured component metadata,
rejects duplicate/unknown fields, wrong source/component, invalid protocol and
mismatched server/CLI protocols. Both actual captured binaries reported d7051cf
and protocol 1 through that interface. The first failed gate issued no passing
receipt and its builder was removed. Native compilation success alone is not
counted as image validation. Two regression tests were added (21 artifact tests).

The corrected second source build completed in 44.84s with native cache reuse,
from bef7ab49dce133fb2fb177d580eb64d748662df5. BuildKit then waited on registry
metadata despite the locally cached pinned base; the bounded command eventually
failed/canceled without producing a passing artifact. This is a packaging
failure, not a successful image or failed engine data test.

Offline packaging now uses a separate no-network/no-mount construction container
from the cached digest (--pull never). Only the two fresh binaries and explicit
LICENSE/NOTICE/upstream README/build receipt are copied. Local Docker commit
sets the runtime user/workdir/entrypoint/help default and operation/source labels;
it never snapshots the compile container, its source, cache mounts or build env.
The generated Dockerfile remains an equivalent review recipe, not a claim that
BuildKit was used for this method. packaging_method records the actual method.
The temporary construction user is root with only CHOWN added after dropping
capabilities; the engine runtime remains UID 1000 with all capabilities dropped.
Actual image checksums and structured component versions are collected inside
the data smoke and compared to the original compiled inputs as an extra gate.

References checked for the exact offline copy/config behavior:

- https://docs.docker.com/reference/cli/docker/container/commit/
- https://docs.docker.com/reference/cli/docker/container/cp/

The first local copy/commit attempt reached construction but failed chmod on
copied binary ownership. It issued no passing receipt; owned resources were
cleaned. The constructor now explicitly chowns only the copied binary/doc files
to root before setting their modes, using its existing CHOWN capability rather
than granting FOWNER or additional runtime permissions. A real separate Docker
probe verified root-owned binaries execute as UID1000 and report the captured
source; its construction container and probe image were removed. The full data
smoke remains a separate required passing gate after this correction.

A subsequent actual package completed image creation but its boundary gate
rejected the Desktop daemon's translated bind Source. A targeted real inspection
confirmed /host_mnt plus the exact macOS client script path, with read-only bind,
UID1000, no-new-privileges and a UID1000-owned data volume. The adapter now accepts
only that exact observed alias on Darwin (ordinary exact paths remain required
elsewhere), and also requires a unique expected script digest in container env.
The wrapper checks the mounted script hash before executing it; copied evidence
must independently match that hash. Other paths, writable binds, missing/duplicate
content identity, root runtime, network/ports and changed scripts remain denied.
Docker's native-path/VM behavior reference:
https://docs.docker.com/engine/storage/bind-mounts/

A targeted copy diagnostic also exposed an asynchronous constructor race: run -d
can return before its initial mkdir finishes. Directory preparation now runs in
a synchronous exec before any copy. Tests simulate delayed initial startup and
require this ordering. Private failure records retain only bounded static reasons
for validation/runtime errors; raw command diagnostics stay in private logs.


2026-10-30 crash-recovery investigation: the actual image built from
8a0d213c95374e3d14cf07431116679f86558fa2 passed source/runtime boundary checks
and initial 4 MiB write/read, but failed simultaneous master/worker SIGKILL
recovery with FileNotFound. No passing receipt or image was retained. A
separate root/host-bind run with the same cached source binaries recovered
4 MiB with identical SHA-256 before/after restart. That comparison does not
validate the non-root image or establish a root cause. Journal acknowledgement,
volume timing and runtime differences remain under investigation; do not add
sleep to hide the failure or restore uncommitted metadata around Raft replay.

Failure evidence contract: collect Docker logs and the synthetic /smoke files
before removing the owned runtime/volume, even after nonzero exit or wait timeout.
A collection failure must never yield a passing artifact. Two regression tests
cover failure/timeout collection and missing diagnostics. All 357 Python tests
pass locally (28 artifact tests); real runtime recovery remains an independent
gate. No persistent infrastructure or customer purchase is authorized by this
local diagnostic work.


Additional evidence, 2026-10-30: the next full pipeline was interrupted during
native linking when the Docker connection returned unexpected EOF. The manager
terminated with failure, no image/receipt, and after Desktop recovery its labelled
builder was found stopped (exit137, OOMKilled=false) and removed. The shutdown
cause was not established; this was not another engine recovery failure.

A separate controlled diagnostic then ran the previously compiled source8a0d213
binaries as UID1000 with a fresh named data volume, read-only root, capabilities
dropped, no-new-privileges, no network/ports and read-only build-cache input.
Their actual SHA-256 matched the earlier captured build receipt. It passed
4 MiB write/read and simultaneous master/worker SIGKILL recovery; payload and
both downloads hashed febb78a42081683639839debffd297bbe5cce29a50a8476a69579a3719546ce2.
Restart replay read committed Raft index9. Synthetic logs were preserved and
owned diagnostic container/volume removed. This is a cached-binary diagnostic,
not a freshly built image artifact or production verification. Consequently
non-root/named-volume failure is not deterministic, and no root cause is claimed.
The asynchronous journal queue and startup replay delay remain candidates to
investigate with deliberate batching/failure injection and a commit barrier test.
Do not weaken recovery gates based on one successful repetition.

Diagnostics collection commit c4b7958a5d6d7418af7dce045d55c5de1756900b was pushed;
CI41029041908 succeeded: https://github.com/Runix-lab/runix-fs/actions/runs/41029041908.
AWS product-tab opening still timed out through the browser extension. No fresh
seller/account/product DOM, change request, live purchase or public visibility
was obtained. Earlier Staging evidence remains historical. No AWS spend occurred.


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
