# Durable negative subscription events

Scope, 2026-10-27: a local internal reducer for direct-sale agreement-ending
and license-deprovisioning events. This is not an AWS event queue deployment,
an activation verifier or a data-plane access revocation implementation.

Accept only configured seller/account, us-east-1, source
aws.agreement-marketplace, AWSMarketplace catalog, a valid event ID/time and
the expected agreement resource. Check buyer/proposer identities, configured
product where present, and license identity for license events. Agreement-end
events may omit product/license; retain buyer/agreement tombstones even before
registration and match them to future verified ResolveCustomer mappings.
License events require the configured product ID and code. CPPO/reseller flows
are outside this first direct-sale scope. Reject active/unsupported events;
do not invent activation from License Updated or ResolveCustomer alone.

These checks validate structure/identity, not origin authenticity. The caller
must be a trusted worker consuming an AWS-authenticated, correctly permissioned
EventBridge/SQS path. Do not expose the reducer as a public JSON webhook or
interpret a source string as a signature. Actual queue/IAM policy validation,
seller registration generation and live event delivery remain release gates.

Transactionally persist minimal immutable event digest/audit, monotone stop
tombstones and quarantine of all pending/sending usage for affected licenses.
Duplicate IDs with the same body are no-ops; changed-body replay is a conflict.
Later negative events may only move the stop boundary earlier. Missing positive
events cannot resurrect a stopped license; a new purchase needs a separately
verified new identity. Do not delete organization bindings, data, source usage,
accepted record IDs or in-flight response evidence.

The stop is durable independently of final accounting. Enforce it when issuing
registration claims/bindings, activating or appending new usage, sealing and
enqueueing, claiming a batch and immediately before SDK dispatch. Already
accepted source-event replays may return their prior no-op result; they add no
new usage. A dispatch already in flight can still return acceptance; preserve
that response separately without undoing the stop or treating it as an invoice.

All pending final usage is held for reconciliation until actual live integration
settlement timing is confirmed. Current AWS subscription and EventBridge pages
disagree about when the one-hour final-reporting period begins. This reducer
does not resolve that disagreement by choosing a speculative deadline, rewriting
timestamps, waiving whole units silently, or automatically releasing held rows.
This safety hold is not a completed final-metering integration and blocks paid
launch until the verified final flush/reconciliation workflow exists.

The boundary is the earlier known event/end time, never receipt-time extension.
Late events that intersect already observed/sealed usage require reconciliation;
do not silently edit immutable quantities. Resource access/provisioning workers
must also enforce the tombstone independently of usage accounting failures;
those workers are not implemented by this reducer.

Tests must cover malformed/foreign events, identity mismatches, pre-registration
events, duplicate/changed/late events, two licenses and agreements, concurrent
stop/enqueue, transaction rollback, process exit/reopen, stopped callbacks,
ledger append/seal rejection and a stop during an in-flight SDK call. No test
may contact production AWS or delete customer resources.

Official sources refreshed 2026-10-27:

- https://docs.aws.amazon.com/marketplace/latest/userguide/notifications-eventbridge.html
- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-eventbridge-integration.html
- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-subscriptions.html

## Local implementation and evidence, 2026-10-28

`scripts/runix/marketplace_lifecycle.py` implements the reducer. The outbox
creates durable agreement/license stop tables and enforces them in registration,
binding, new usage activation/append, sealing, enqueueing, batch claims and the
pre-dispatch lease check. Existing organization views expose stopped state
without deleting their purchase mapping or source data.

Twenty-one new tests passed, bringing the combined suite to **118 passed**.
They exercise malformed/foreign/positive-event rejection, direct-sale identity,
pre-registration events, two agreements/licenses, duplicate/changed/late events,
failed quarantine rollback, concurrent stop/enqueue, process exit/reopen and a
stop while an SDK request is already in flight. The latter keeps the response
audit but leaves the usage held, and the worker does not report completed local
dispatch. A direct guard also rejects an ended agreement before any local
license mapping has been created.

The first attempted rerun failed at import because the earlier /tmp environment
no longer had boto3/PyYAML. A package install correctly refused to modify the
externally managed Python. Created a new isolated environment at
`/tmp/runix-marketplace-verify-20261028`, installed the fixed SDK requirements
and PyYAML 6.0.2, then ran the full passing suite there. This is local runtime
recovery, not an SDK-free test pass or a change to system Python.

No live EventBridge/SQS transport, resource revocation, customer-data deletion,
accepted-charge refund, final-flush release or AWS purchase is exercised here.
Those remain production gates; retained pending intents must never be consumed
without fresh license verification and stop checks by a real provisioner.
