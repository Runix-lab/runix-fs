# Local offline backup and fresh-boundary restore gate

Scope, 2026-10-29: real synthetic integration, not a production backup service.
Use cached immutable images and the existing WAL-repaired binary build. No AWS,
public ports, privileged containers, image downloads or paid resources.

Prepare an original independent S3-compatible store and actual engine using the
existing seed/read/write/crash-recovery runner. After engine exit, export both
known synthetic objects through an independent SDK with fixed names, bounded
sizes and SHA-256 manifest. Copy stopped engine metadata, journal, worker data
and configuration to a fresh runtime folder, plus object export and independent
expected payloads. Never copy an open RocksDB or a running worker directory.

Remove original engine/store/network and verify their absence before creating
the restore environment. Start a fresh object store with the fixture credentials
required by the backed-up mount metadata, import objects only after validating
the complete manifest and bytes, then boot the real engine from copied state.
The restored container must have no original-state mount or network attachment.
No formatting, fake reconstruction of metadata, or reseeding missing original
objects on read failure. Read and compare both existing files and write a new
independent payload; an SDK read directly from the fresh object store must match
that new payload, proving writes use the restored backend.

Restrict export/import to the two known 4 MiB fixture keys. Reject unexpected or
truncated listings, wrong manifest fields, sizes/hashes and missing/corrupt data.
Validate the complete import before creating its bucket or writing any object.
This manifest checks integrity, not authenticity, encryption or a secure archive
format. Runtime, credentials, database files and raw logs stay out of Git.
Use fresh private folders, bounded processes, unique resource names and cleanup
on all failures. Confirm cleanup with successful Docker inventories. Preserve
unrelated services. Never print secrets from fixture environment or mount logs.

Unit tests cover complete export/import, corruption of either object without
partial import, path/manifest substitution, unexpected object listings, partial
source export and scoped cleanup failures. Actual runtime evidence is separate:
record original resource removal, restored file/new-write hashes, binary hashes
and cleanup outcome only after execution.

The stopped state and full local object export form a synthetic offline recovery
point. This is not online snapshots, AWS S3 versioning/IAM, scheduled backups,
production encryption/retention/export policy, cold-cache rehydration, FUSE, HA,
RPO/RTO/SLA, real subscription cancellation or a delivered SaaS service.

## Actual result, 2026-10-29

**Passed twice locally**. The final run adds mandatory independent SDK readback
of every imported object rather than relying on PutObject acknowledgement.
Original engine container exit was checked before copying database/state files.
Original container/network inventories were checked empty before creating the
fresh restore store. Restore mounts only the new state folder, read-only build
volume and repository fixture scripts, with no original network or data mount.

Recovered files and a new post-restore write each had 4,194,304 bytes:

| Payload group | SHA-256 |
| --- | --- |
| Exported source / imported object / restored engine read | `fdeeef4b42e7679eb2cc8ab1b608209f603c0e94c1ec456c6788f54c9dce3f9e` |
| Exported upload / imported object / restored engine read | `80e456ac3ec51e8974c2cbe46ceadc4f93c1cc57d5886c1cebc097a6bbf5dd45` |
| Fresh post-restore write / engine read / direct object-store read | `a9c5ffa73dfc686892a2d3600b27fab7ee428a36442fb577979f83cbe02ce846` |

Server SHA-256:
`707497ccfd450d5c7f6c252230819d0c4a9297328d74207b44f2bc2f4c640914`.
CLI SHA-256:
`f1f517005f18b5157c017d1759b0c5448a1efac9da3babc12a1f5b9f3f50dd12`.
These reuse the previously WAL-repaired engine build; no new Rust source or
latest-commit engine rebuild occurred. Images are the cached immutable digests
already recorded in marketplace-local-smoke.md.

Final private evidence directory (not committed):
`/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-backup-smoke-22uysjtd/`.
First successful run before adding complete imported-object readback:
`/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-backup-smoke-0hx1yd7n/`.
The final evidence reports original_removed_before_restore=true and
cleanup=verified_removed. Independent fresh Docker inventories then confirmed
zero owned containers/networks, and the temporary fixture credential file was
gone. Unrelated services were preserved. No AWS calls/resources or purchases.

Runner source SHA-256:
`05fcf532182e0b1f6eb6f7074f6eba9514076293f9e78a0b2bddc4427c78b2f0`.
SDK fixture SHA-256:
`b958770712e5ce4bcc4e9a50c23baa2d46439b50c349997ab3da01ca9fa90cca`.
Restore shell SHA-256:
`d51fe7f2e5d095d2c92e7e51f498ce6e764e2cd4c4ea62f763adbb6999486048`.

Reproduce with the already installed SDK, images and build volume:

```sh
/tmp/runix-marketplace-verify-20261028/bin/python scripts/runix/local_backup_smoke.py \
  --sdk-dir /private/tmp/runix-marketplace-verify-20261028/lib/python3.14/site-packages
```

Fifteen new unit tests pass, covering both object import/export and orchestration
failure/cleanup boundaries. Complete Python suite: **193 passed locally**.
Shell syntax, Python compilation, provenance and whitespace checks pass.
These are local fixture/recovery tests, not implementation or acceptance of a
production backup/retention policy. The restore retains worker cache too, so it
does not establish cold-cache recovery from object storage alone. Marketplace,
IdP, active-license verification, production delivery and buyer tests remain
separate unfulfilled requirements.
