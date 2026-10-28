# Website and account integration

## Migration delivery

Canonical marketing page: https://runixcloud.io/fs
Existing product mirror: https://fs.runixcloud.io
Documentation: https://runixcloud.io/docs/fs
Source: https://github.com/Runix-lab/runix-fs

The repository homepage links to the canonical page. The marketing page and
quick start must link back to the Runix fork and retain Curvine attribution.
Upstream benchmark source links must continue to identify upstream results.
Upstream releases remain explicitly upstream releases until Runix publishes
its own verified artifacts. Website wording must not imply a live AWS listing,
available SaaS console or shared account system that has not been implemented.

Website source lives in the separate `cuihuan/runix-site` repository. Product
metadata is maintained in `tools/stack.py` and `tools/product_template.py`.
Edit canonical sources where applicable, rerun the generator and check a second
run for idempotency. Run site QA and inspect the exact diff before publication.
The existing Pages deployment is a direct upload; verify remote ancestry and
live content first. Main site and product mirrors have separate deployments.

## Future authenticated experience (design only)

Keep the public page static. Link Get started to a Runix account portal only
after it is deployed. Reuse an existing Runix identity provider only after its
actual protocol, session boundary and tenant ownership model are confirmed;
the inspected marketing site does not establish an existing shared SSO service.

The future control plane owns accounts, organizations, memberships, cluster
provisioning, API credentials, audit history and entitlement state. The website
contains no AWS credentials. A dedicated HTTPS backend receives Marketplace
registration POSTs, resolves the token immediately, binds the agreement to an
authenticated Runix organization and returns an opaque, short-lived redirect.
Never put registration tokens in URL query strings, analytics or static logs.

Route plan (local implementation does not establish public deployment):

| Route | Owner | Test obligations |
| --- | --- | --- |
| `POST /marketplace/register` | Commerce backend; local WSGI JSON handoff implemented | Valid/invalid/expired token, product mismatch, replay, cross-tenant binding |
| `GET /api/fs/organizations` | Local control-plane API | Actual JWT signature and fresh subject membership |
| `GET /api/fs/purchases` | Local control-plane API | Org membership, cross-org denial, stopped/pending state |
| `POST /api/marketplace/bind` | Local control-plane API | Signed identity, admin membership, opaque claim, replay/concurrency |
| `GET /api/fs/entitlements` | Control plane | Auth, organization role, stale/expired entitlement, concurrent agreements |
| `POST /api/fs/clusters` | Control plane | Authz, idempotency, capacity reservation, denied entitlement, rollback |
| `GET /api/fs/usage` | Control plane | Tenant isolation, time boundaries, estimated/pending/final semantics |

Endpoint tests are mandatory when these routes are implemented. Do not add
placeholder handlers returning success during migration. Keep management RPC,
worker traffic and upstream Web UI private; expose only the authenticated Runix
API and user-appropriate views. Service domains, identity provider and final
pricing remain implementation decisions, not DNS changes performed here.

Local progress, 2026-10-27: marketplace_registration.py now implements pending
claims and durable membership/binding logic beneath the proposed HTTP routes.
Its Principal parameter requires a verified future authentication context;
it does not implement a login service. Subsequently added the actual signed
access-token verifier and local WSGI registration/binding/read endpoints; see
control-plane-auth.md and control-plane-http.md. Loopback HTTP tests use real
signatures and SDK Stubber, not actual Marketplace buyers. No route in the table
above is deployed or ready as a public Marketplace fulfillment URL. Browser
account setup, provider configuration, positive activation and provisioning
remain mandatory gates.
