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
