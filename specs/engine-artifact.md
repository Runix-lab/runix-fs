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
