# Local control-plane HTTP boundary

Scope: connect signed access-token verification, real SDK registration and the
durable purchase registry through an actual WSGI application. This is not a
production deployment, browser OAuth login, positive license verifier or cluster
provisioner. No route returns successful cluster creation or a fake endpoint.

Routes:

| Method/path | Behavior |
| --- | --- |
| POST /marketplace/register | Consume only the form x-amzn-marketplace-token, call real configured RegistrationGateway, return a short-lived claim with pending_account_binding status (202) |
| GET /api/fs/organizations | Verify bearer signature/profile, then list the subject's current DB memberships |
| GET /api/fs/purchases?organization_id=... | Verify identity and fresh membership before returning only that organization's pending/stopped purchases |
| POST /api/marketplace/bind | Verify identity/admin membership and exact JSON {organization_id, claim}; atomically bind and return pending_license_verification status, never provision |
| GET /health/live | Process responds; no delivery/activation claim |
| GET /health/ready | 503 delivery_not_configured until real provisioning/license/client integration exists |

TLS is mandatory except an explicitly configured HTTP loopback origin with a
loopback peer. Host must exactly match the configured origin. Never trust an
arbitrary X-Forwarded-Proto/Host header. JSON APIs reject a foreign Origin and
use Authorization Bearer only; cookies and query tokens are never credentials.
Do not enable CORS or accept state-changing form submissions on signed APIs.
AWS registration is the deliberate cross-origin form exception; its temporary
token is verified by ResolveCustomer, not by an Origin header.

Validate methods/content types/UTF-8/content lengths and body limits before
parsing; reject duplicate JSON keys, repeated/missing form tokens, extra buyer
AWS identity fields, ambiguous query parameters and unsupported transfer
encoding. No unbounded stream read. Use no-store, no-referrer, nosniff and a
restrictive CSP. Do not log raw Authorization, form bodies, claims, query
strings, SDK exception messages or decoded subjects. Error responses are static
and sanitized. No request-supplied value controls an outbound URL or DB path.

Open a separate private SQLite connection per request, always close it, and
derive issuer/seller/product from fixed server configuration. Read/bind APIs
can operate on existing mappings if AWS registration is unavailable, but the
callback must return 503; it must never synthesize a purchase. A missing signer
configuration is a startup error, not an authentication bypass. Membership
creation/removal stays operator-only, with no HTTP bootstrap/admin mutation.

Tests: all endpoints' happy/denied/validation/unavailable paths, real RSA
signatures and SDK Stubber, role revocation/cross-org access, wrong seller,
callback/bind replay, stop guards, partial failure and concurrency. Include an
actual loopback HTTP server request cycle, not only direct function calls. Use
synthetic purchase fixtures and ephemeral keys; no real purchase or AWS API.

The registration JSON handoff still needs a complete browser account setup
experience. Do not configure this bare API as a public Marketplace fulfillment
URL or treat process liveness as delivery readiness. Public registration needs
real IdP configuration, OAuth/browser flow, TLS deployment, quota/provisioning,
positive activation and real seller/buyer tests before review submission.

## Implemented and verified, 2026-10-28

`scripts/runix/control_plane_http.py` implements these routes. Twenty-two new tests
pass, including an actual temporary loopback HTTP server with real signed JWTs,
registration through SDK Stubber, binding and organization reads. They cover
all routes' denied/validation/error behavior, content limits, TLS/Host/Origin
checks, token/role revocation, concurrent binding and transaction failure.
The combined Python suite has **153 passing tests**. The server and ephemeral
keys are shut down at test completion. No persistent preview URL is claimed.

RegistrationGateway's normal-session factory now sets 3-second connection and
5-second read timeouts, two total standard-mode attempts, and ignores configured
endpoint-URL overrides. Factory tests check this for both registration and the
retained Contract adapter. This is not a whole-request wall-clock guarantee;
production still needs a vetted TLS/WSGI server, request timeouts and abuse
controls. The development runner binds only 127.0.0.1, never a public interface.

The runner accepts only an explicit operator-verified JSON configuration with
database, seller_account, product_code, issuer, audience, client_ids, jwks and
public_origin. No real IdP/client/JWKS configuration is shipped or invented.
Use the normal boto3 role/SSO credential chain; do not add AWS keys to the
configuration. A missing configuration/AWS seller identity fails startup.

Example command shape (the config must first exist and be verified):

```sh
python scripts/runix/control_plane_http.py --config /operator/path/control.json --port 8091
```

There is no live browser OAuth setup/redirect flow in this API. A 202 registration
response proves pending identity handoff only, and 200 binding proves a durable
pending intent only. `/health/ready` remains 503. No cluster create endpoint or
service connection details are fabricated, and this API is not submitted as the
Marketplace fulfillment endpoint.

SDK timeout reference checked against the installed service model/config:
https://docs.aws.amazon.com/botocore/latest/reference/config.html.
