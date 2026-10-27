# PAYG durable metering boundary

Status: local implementation scope, 2026-10-26. This is not a deployed billing
service, storage collector, authenticated organization API or license verifier.
It is the durable outbox required by commercial-service.md stage 5.

## Input contract

Only a trusted future control-plane worker may enqueue a **sealed** hourly
quantity derived from the logical byte-time ledger. The worker must first verify
the purchase, active PAYG license, organization binding and usable provisioning.
Buyer-provided identifiers or quantities are never valid inputs. These upstream
systems are not implemented by an outbox. No HTTP listener or scheduler is added.
No real AWS billing request runs from tests or from an automatic CLI command.

Quantity is an integer 0..2147483647; boolean/float quantities are rejected.
`Timestamp` is an aware, second-precision time, normalized to UTC, no earlier
than the actual service usage. Identity is unique per license, dimension and
UTC hour. Different quantities or buyer/agreement/timestamp for the same key
are a conflict, never an additive charge. License/account/agreement identity is
also bound across all hours and dimensions. Replay within the reporting window
returns the existing row, including accepted rows, without dispatching again.
Zero-quantity records are allowed. No float conversion or rounding occurs here;
fractional GiB-hour integration belongs in the collector/ledger implementation.

## Persistence and dispatch

SQLite on local persistent disk uses WAL, synchronous FULL and explicit
transactions. One database is bound to one seller/product and a schema version;
opening it with a different configuration fails closed. This is a single-host
database, not shared-network-filesystem or distributed-HA storage. Runtime DBs
and their WAL/SHM files must never enter Git. Use an operator-owned mode-0700
runtime directory, for example the ignored `.runix-runtime/`. The database is
created mode 0600; world/group-readable files and final symlinks are rejected.

An atomic claim leases at most 25 rows for one worker. Each attempt is recorded
before leaving the transaction. The AWS call runs outside the database lock.
An expired lease can be reclaimed after a crash, always with the exact frozen
payload. A stale worker cannot overwrite the new attempt or terminal state.
The worker checks its configured seller account using STS before any metering.
Concurrent Agreements records contain CustomerAWSAccountId and LicenseArn;
ProductCode and CustomerIdentifier are never sent.

Rows expire at the earliest of Timestamp+24h, next-month 06:00 UTC, and any
explicit final-settlement deadline supplied by the verified lifecycle worker.
An expired row is quarantined instead of poisoning an entire batch. The worker
must dispatch well before the deadline; the final pre-send check cannot ensure
network arrival before it. No assumption about the conflicting cancellation
event timing is introduced here. The lifecycle integration must shorten pending
deadlines immediately on a verified end event; no new usage may accrue after
the cancellation boundary. This integration remains a release gate.

Process each response row separately. Success requires an exact echoed record
and a nonempty MeteringRecordId. DuplicateRecord and CustomerNotSubscribed are
quarantined for reconciliation, not counted as billed. Unprocessed or missing
rows retry unchanged. Foreign, altered, duplicate or contradictory response
records invalidate the response without partial database updates. Retryable
transport/internal/throttling errors retain the frozen rows; permanent errors
are quarantined. Accepted records never regress. Valid remote results arriving
after deadline or lease expiry are retained in a separate response audit for
reconciliation without overwriting current state. A successful API result is
**accepted usage**, not an AWS invoice or proof of final settlement.

## Test requirements

- Identity/quantity/time validation, seller mismatch and SDK service shape.
- Same-hour replay/conflict, two licenses for one account, configuration mismatch.
- Independent database connections racing for rows; leases and stale completion.
- SQLite process exit after claim; restart/retry preserves quantity and key.
- Batch partial success, missing/unprocessed rows, duplicates, foreign records,
  SDK failures, permanent rejection, no legacy fields, no real network calls.
- UTC offset normalization, 24h boundary, month rollover/06:00 cutoff, shortened
  cancellation deadline; no dispatch of expired records.

Sources refreshed 2026-10-26, against installed botocore 1.43.118:

- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_BatchMeterUsage.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_UsageRecord.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_UsageRecordResult.html
- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-integrate-subscription.html

AWS explicitly describes DuplicateRecord as the same customer/dimension/time
with a **different quantity**; it must not be silently treated as success.

## Local verification, 2026-10-27

Implementation: `scripts/runix/marketplace_metering.py`; 26 unit tests in
`test_marketplace_metering.py`. Tests use the installed SDK model and Stubber,
independent database connections, a real subprocess exit and injected SQLite
transaction failures. Remote acceptance followed by a failed local commit
retries the exact record after lease expiry. Combined Python suite: 59 tests.
These results do not constitute the separate independent financial/security
review, seller-account metering acceptance or invoice reconciliation required
before paid activation.

## Storage interval ledger implementation scope

Add a private, internal `StorageUsageLedger` sharing the outbox's SQLite file.
Its trusted caller must authenticate the organization and verify the PAYG
license and usable provisioning before activating a stream. This does not
replace those controls and is not exposed as a buyer API. Binding is immutable
per license/account/agreement. No data accrues before explicit activation.

Inputs are completed, authoritative constant-usage intervals [start,end), in
integer logical live bytes and second-precision UTC. They must be contiguous,
at most one hour long each, and no later than the supplied current time. An
unobserved gap is an error, never assumed to contain zero bytes or extrapolated
from an old sample. Source-event IDs are idempotent within a license; altered
replays, overlaps, stale ordering and cross-buyer rebinding fail atomically.
Actual engine mutation collection, source authentication, sparse-hole exclusion
and coverage proof remain missing; `cv fs count` alone is insufficient for this
definition. Never describe caller-supplied synthetic intervals as live metering.

Accumulate byte-seconds using exact Python integers, stored as decimal TEXT to
avoid SQLite signed-integer overflow. Seal only fully observed UTC hours, plus
a final observed partial hour on cancellation. Divide accumulated byte-seconds
plus prior remainder by (2^30 * 3600). Keep the remainder per license, without
floating-point rounding or per-sample ceiling. Final settlement records and
waives the sub-unit remainder. No new interval or reopening is allowed after
closure. Late lifecycle corrections need reconciliation; this primitive does
not discover or implement cancellation events.

Sealing, remainder updates, closed-state transition and enqueueing immutable
AWS records must use one SQLite transaction; nested outbox work uses savepoints.
A failure after any enqueue rolls back the entire seal. Concurrent callers
must not consume the same remainder twice. Reject mixing manually enqueued
records with activation of this ledger's fixed storage_gib_hour dimension.
Use the actual service start if activation occurred within the first hour;
never backdate a record to before activation. Deadlines remain the outbox's
current AWS limits plus a caller-supplied verified final-settlement deadline.

Required tests: exact fractional carry across hours, no per-sample rounding,
final waiver, zero usage, month/timezone boundaries, validation, failed binds,
duplicate/conflicting/reordered events, gaps, concurrent append/seal, closure,
partial enqueue failure rollback, process exit/reopen and the complete local
ledger -> immutable outbox -> SDK request path. All SDK calls remain stubbed;
no paid billing or deployment is authorized by passing these tests.

### Implemented interval-ledger verification, 2026-10-27

`scripts/runix/marketplace_storage_usage.py` implements the scope above, with
19 tests in `test_marketplace_storage_usage.py`. Combined Python suite: **80
passed**. Tests cover changing capacity against an independent Fraction
reference, byte counts beyond binary floating-point precision, exact carry,
final waiver, immutable replay, same-account concurrent licenses, source gaps,
cross-buyer rejection, transaction fault injection, process exit/reopen,
parallel writers/sealers and an actual botocore Stubber request derived from
intervals through the worker. All intervals/identities are synthetic fixtures;
no deployed cluster collector, HTTP interface or real AWS charge was used.

Nested savepoints in the existing outbox allow sealing several hours and their
remainder/state in one outer transaction. Tests inject a failure on the second
outbox insert and verify the first insert and remainder also roll back. Sealed
usage is immutable; the ledger does not invent replacement charges for stale
or conflicting inputs. Delayed collection that misses AWS deadlines requires
operator reconciliation, not timestamp rewriting to make old usage billable.

Important lifecycle boundary: closing the *accounting stream* successfully is
not a subscription-cancellation implementation. The future lifecycle service
must durably enforce cancellation and deny new usage independently of any seal
or AWS-reporting failure. A cancellation arriving earlier than already observed
or sealed usage requires reconciliation/quarantine before dispatch; this ledger
does not silently edit intervals or previously accepted bills. These controls,
trusted measurement provenance, production deployment and independent financial
review remain paid-launch gates.
