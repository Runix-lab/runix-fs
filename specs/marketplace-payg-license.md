# PAYG license event and fresh agreement check

Scope, 2026-10-29: internal local reducer and verification worker component.
No deployed event transport, activated cluster, public license API or billing
scheduler. Existing pending intents remain pending; a successful internal check
is short-lived evidence, never an allocated resource or customer delivery claim.

New primary evidence: the rendered 2026 Concurrent Agreements workshop, Task 3
under Contract with Consumption / Subscription (pay-as-you-go), explicitly
identifies License Updated - Manufacturer as active entitlements eligible for
usage reporting and License Deprovisioned - Manufacturer as the ending signal.
Task 2's PAYG tab skips Contract GetEntitlements. This supersedes the earlier
uncertainty caused by inspecting the generic event example alone. Do not use
buyer-oriented GetAgreementEntitlements as a guessed seller activation API.
Source, retrieved in the browser on 2026-10-29:
https://catalog.workshops.aws/mpseller/en-US/saas/integration-for-concurrent-agreements

Reuse strict event envelope and purchase-identity parsing from the negative
reducer, with an explicit update-only caller. Default negative apply still
rejects positive events. Both use the same immutable event-ID/body audit;
changed-body/cross-kind replay conflicts. Record updates and immutable license
identity atomically, including before registration. Preserve latest event time
monotonically; old events may be audited but cannot move it back. Negative stop
tombstones never clear, even if an update arrives later. JSON validation is not
source authentication: only a trusted future worker with verified AWS transport
may call this internal reducer. No public JSON webhook accepts these events.

Before returning provisioning eligibility, load an existing organization-bound
pending intent and matching update/purchase under the database transaction. Check
stops and mapping, then query AgreementReader outside the write transaction.
Require configured direct seller/product and a currently ACTIVE started agreement
with an unelapsed optional end. Recheck database mapping and stops after the AWS
read, using a fresh trusted clock. A local 30-second observation bound is a
conservative implementation freshness limit, not an AWS SLA or long-lived grant.
No resource consumer accepts this check as a reusable capability. A future real
provisioner must check again before actions and enforce cancellation itself.

AWS failure, inactive/future/expired agreement, missing event/binding, foreign
identity or cancellation denies eligibility without a success placeholder. No
Contract capacity, storage quota, provisioning completion, usage permission or
customer-data deletion is inferred. Live queue/IAM authenticity, missed-event
reconciliation, deployed resource access enforcement, final metering and buyer
testing remain release gates; no production readiness follows from offline tests.

Tests: event identity/format validation, replay/body conflict across reducers,
pre-registration updates, immutable identity, out-of-order updates, cancellation
before/after/during verification, two licenses under one account, unauthorized
organization binding, expired/changed mappings, fresh clock/end boundaries,
SDK-modeled responses/errors, concurrent reducers and process restart/rollback.

## Local implementation evidence

Implemented marketplace_payg_license.py and expanded the existing private event
parser with an explicit update-only path; default negative behavior is preserved.
Twenty-seven new tests pass, bringing the complete Python suite to **220**.
Tests use botocore DescribeAgreement models/Stubber, separate SQLite connections,
actual subprocess exit without cleanup, transactional audit failure and a
cancellation committed from another connection during the AWS call. Eligibility
is denied after that stop; no DB write lock is held across the external read.

These tests use trusted synthetic event fixtures and SDK responses. They do not
authenticate a real EventBridge message, exercise a real agreement, grant cloud
access or launch a cluster. The public HTTP API continues to show the durable
pending state. No fulfillment URL, customer license or Marketplace publication
state was modified by implementing this component.


Caller-transaction guard, 2026-10-30: check_pending rejects an existing outer
transaction before making an AWS read. Its own pre/post snapshots cannot release
an outer caller's transaction; allowing that composition would retain a write
lock or stale snapshot during network verification. A regression test verifies
that the agreement reader is not called. The new provisioning journal also reads
its trusted clock after acquiring the mutation transaction, so lock waiting
cannot extend observation freshness or revive an expired work lease. These are
internal fencing controls, not resource creation or real license acceptance.
