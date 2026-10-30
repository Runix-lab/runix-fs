# Durable provisioning work journal (internal, not delivery)

Scope, 2026-10-30: establish the durable boundary needed before connecting a real
resource driver. Existing registration intents remain pending. No cluster, access
credential, endpoint, billable usage or successful provisioning response is
created by this component. Public readiness remains503. Provider creation,
resource adoption/rollback, real access suspension and buyer tests remain gates.

Pin one explicit local-acceptance profile (image/source identity) and an operator
allocation-slot limit to the existing private commerce database. This limit is
not a storage-byte quota, Contract entitlement or AWS budget. Profile changes
require explicit migration; no silent reinterpretation of existing work.

Reserve one work item per already organization-bound pending intent/license,
after the real PaygLicenseState fresh check. Recheck identity/stops/freshness in
the write transaction; never hold that lock during AWS calls. Store a random
internal operation key, not an invented AWS resource ID. Replays retain that key
and slot. Concurrent reservations must not overbook slots. Do not release a slot
on timeout, error or cancellation: future provider reconciliation must first
establish what resources/data exist. No data deletion is implemented.

A worker claims a bounded, random, epoch-fenced lease after another fresh check.
The lease expires no later than that check's conservative observation window.
An expired lease can be reclaimed with a higher epoch and the same operation key.
Renewal must check AWS outside the write lock and recheck the current token,
epoch, organization/license binding and stops afterward. Never revive an expired
lease or accept an old worker's result. Lease handles are internal coordination,
not customer authorization or positive resource-creation receipts.

Failures can requeue work with a fixed sanitized reason while retaining the slot.
A reducer marks known negative lifecycle stops as stop_requested, clears leases
and advances the epoch atomically. Replay must be harmless, and clock rollback
must not delay this negative fence. stop_requested does not mean an actual
cluster has been stopped; the future real driver must enforce it. No method
marks work active/created/suspended until actual resource evidence exists.

Audit transitions in the same transaction. Do not store/log raw SDK errors,
registration/access tokens or lease secrets in audit/repr. This module is not an
arbitrary public method dispatcher: organization authorization remains in the
existing verified registration/API boundary. No endpoint is added here.

Tests: invalid/mismatched profile and issuer/product configuration; unauthorized
binding and missing/stopped/inactive purchases; idempotent reservation and slot
concurrency; lease expiry/renewal/takeover, old tokens/epochs, time rollback;
negative events during external reads; changed organization mapping; atomic audit
failure; separate database connections; actual process exit after reservation and
claim. Also assert registration remains pending and usage/resources are absent.
Then implement and test the real private driver against this journal before
claiming any provisioning or cancellation enforcement.


## Local implementation evidence, 2026-10-30

marketplace_provisioning.py implements this internal journal. Thirty new tests
pass, including separate SQLite connections, concurrent replay/claim/slot races,
audit failure rollback and an actual subprocess exiting with os._exit after
committed reservation/claim. The operation identity/slot survive; takeover uses
a higher epoch. Raw lease tokens are hidden from repr/audit, and fixed failure
codes do not retain SDK bodies. Tests use real registration/negative/PAYG reducers
with synthetic agreement snapshots; they authenticate no live buyer/license.

Positive mutations read the trusted clock only after acquiring their transaction.
Waiting for that lock can expire an AWS observation or an old lease; regression
tests inject that delay before reserve/renew/current/failure checks. PaygLicenseState
now rejects an already open caller transaction before any AWS read (one new
component test), preventing an outer transaction from retaining locks/snapshots
across network verification. All397 Python tests, provenance/migration and
whitespace checks passed locally.

No resource driver, active/suspended cluster state, slot release, data deletion,
public route, delivery readiness or new usage was implemented or claimed. The
profile is explicitly local-acceptance metadata, not a production deployment or
billable capacity offer. Provider creation/adoption, rollback, resource fencing,
hard byte quotas, deployed access control and independent adversarial review
remain required before commercial activation. No AWS resource or purchase.
