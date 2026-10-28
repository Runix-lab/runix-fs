# Registration identity and organization binding

Scope, 2026-10-27: real SDK token resolution plus durable pending purchase and
organization binding, without HTTP, production identity provider or provisioning.
This is a local control-plane component, not an operational registration URL.

Split token resolution from Contract entitlements. A RegistrationGateway verifies
the caller's seller STS account, resolves a nonempty token, and requires the
configured product, buyer account, license and agreement. It does not call
GetEntitlements or grant an active PAYG license. Preserve ContractGateway's
existing interface/tests while reusing this resolver.

Registration creates a high-entropy, short-lived opaque claim. Store only its
SHA-256 digest and resolved purchase mapping; never persist/log the raw AWS
registration token or claim. Enforce one immutable account/agreement identity
per license. Each successful callback may issue a new pending claim for the
same purchase, but claims never create multiple bindings or provision clusters.
Return the claim only to the future secure registration frontend; TTL <=15min.

Binding requires a principal from **verified future authentication middleware**
and an owner/admin membership in the chosen Runix organization. Memberships are
durable and revocable; no buyer can assign themselves membership through this
module. Operator membership management is an internal bootstrap interface,
not a public HTTP route. The principal structure merely carries the verified
issuer/subject and expiry; constructing it does not verify a JWT or authenticate
a real user. A fixed configured issuer, nonempty subject and unexpired context
are required, along with fresh DB membership checks on every operation.

Bind a license to at most one organization, with immutable account/agreement
identity. Same-organization replay is idempotent; cross-organization claim
replay or an unauthorized caller fails. Read/list APIs authorize membership
and never expose another organization's mapping. Use random opaque claim IDs,
strict parameter validation, no buyer-supplied AWS account IDs or LicenseARN
substitution, and no resource creation on ResolveCustomer success alone.

Every state mutation is transactional in the existing private SQLite outbox
file. Binding and a single provisioning-intent row are committed together;
intent is **pending_license_verification**, never successful provisioning.
An intent is only a durable future work item. No worker returns a fake cluster,
endpoint or success. Cancellation/expiry requires the future verified lifecycle
state machine and independently enforced resource access.

Tests: actual botocore request/response models; wrong seller/product; invalid,
expired and missing metadata; no Contract entitlement call for PAYG resolution;
anonymous/wrong issuer/expired context, member role and revoked membership;
claim validation/expiry/replay, immutable identity, cross-org access, concurrent
binding, process exit/reopen and rollback of a partial binding/intent insert.

Official sources checked 2026-10-27:

- https://docs.aws.amazon.com/marketplace/latest/userguide/saas-integrate-subscription.html
- https://docs.aws.amazon.com/marketplace/latest/userguide/notifications-eventbridge.html
- https://docs.aws.amazon.com/marketplacemetering/latest/APIReference/API_ResolveCustomer.html

The current EventBridge guide still conflicts with subscription pricing docs
about the start of final-reporting time, and License Updated examples alone
do not prove current active PAYG state. Do not invent an activation rule from
ResolveCustomer or use Contract GetEntitlements to fill that gap. Live seller
event transport, fresh reconciliation, authenticated HTTP/CSRF/redirect handling
and real buyer testing remain required before configuring a fulfillment URL.

## Local verification

Implemented `RegistrationGateway` and `RegistrationRegistry`, with 17 new tests.
All 97 Python tests pass, including unchanged Contract adapter tests. New tests
use actual botocore ResolveCustomer shapes and Stubber, separate-connection
binding races, a real process exit, revoked memberships, claim expiry and a
fault after purchase insertion but before intent insertion. Raw synthetic AWS
tokens and returned claim values do not appear in the SQL dump. No real token,
buyer, authentication session or AWS request is used.

`Principal` is an internal verified-authentication context contract, not a
working SSO implementation. Tests construct synthetic contexts deliberately;
passing them does not prove deployed identity-provider integration. Issuer is
fixed per database and contexts must expire within 15 minutes. Membership
management remains an operator bootstrap method without an HTTP listener.
No active license, resource, metering job or buyer-visible console is produced.

Local authentication progress: control_plane_auth.py now constructs Principal
from an actually verified RS256 access token, with fixed issuer/audience/client
and time/scope checks. See control-plane-auth.md. This replaces caller-made
contexts at the future API boundary; it does not configure a real Runix IdP,
OAuth browser flow or public HTTPS registration endpoint.

Subsequent local HTTP implementation is recorded in control-plane-http.md:
registration 202 and binding 200 are real durable pending states, not active
licenses or provisioning results. The registry can serve existing authenticated
organization reads without a registration gateway; attempting to register while
that gateway is unavailable fails with 503 through the HTTP layer. Actual browser
SSO, live seller calls and customer resource creation are still unverified.
