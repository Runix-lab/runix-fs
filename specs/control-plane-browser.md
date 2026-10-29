# Browser account, session and pending-purchase handoff

Implementation contract, 2026-10-29. This extends the local control plane; it
never changes API bearer authentication or marks delivery ready. Production
budget is declined. No new IdP/client/domain, cloud resources or legal identity
is created. Existing website and shared identity services stay untouched.

An explicitly configured BrowserAccountApp wraps ControlPlaneApp. Its HTTPS
OIDC issuer must match the pinned API/registry issuer; its exact redirect URI
must be public_origin/account/callback. No request can select a provider or a
return URL. The separate browser routes use opaque random sessions stored only
as digests in the existing private database, with fixed origin/issuer settings.
Session expiry never exceeds verified Principal expiry (at most 15 minutes).
No refresh, remembered device or idle extension is invented.

Use Secure, HttpOnly, Path=/, SameSite=Lax and __Host- cookie names on HTTPS;
never Domain. Explicit HTTP loopback development uses distinct local names and
must retain the existing Host/scheme/peer validation. Production endpoints
cannot opt out of HTTPS. Reject duplicate/invalid owned cookies. All responses
are no-store/no-referrer/nosniff/frame-denied, with scripts disabled by CSP.
GETs must not change purchase/organization authorization. Escape every rendered
identity and database value, reuse the original Runix logo and serve only fixed
local assets. No client-side SDK/API tokens or AWS claims are put in URLs.

GET /account displays the real database state or a sign-in form. Sign-in POST
requires exact Origin and a random prelogin cookie/form CSRF match, then rotates
a browser correlation secret and starts code/S256/nonce login. Callback consumes
state before exchange, verifies signed identity and rotates/revokes the old local
session. A pending purchase digest is pinned into OIDC state and the resulting
session; changing/removing/inserting a pending cookie across login denies the
callback. No provider admin/org claim creates a Runix membership. Callback URLs,
codes and exception text must never be logged by a deployment server.

All authenticated form POSTs require exact Origin, a session-bound CSRF cookie
and matching form token. Fresh database membership authorizes each purchase
read/bind. Cookies cannot authenticate the existing /api routes. Logout revokes
the session durably and clears browser credentials; it does not pretend to log
out the IdP or revoke unrelated devices.

A narrow authenticated create-personal-organization operation creates one
server-named owner workspace per subject, with no caller-chosen ID, subject or
role, no legal entity claim and no resources/cost. Repeat/concurrent requests
return that same workspace. Never restore a revoked/downgraded membership on
repeat. Existing arbitrary membership editing remains operator-only. Add no
unauthenticated or general-purpose role assignment endpoint.

The browser Marketplace POST resolves the actual AWS token through the existing
gateway and stores only its opaque short-lived claim in an HttpOnly cookie,
then redirects to /account. Raw AWS token is never stored. Binding uses that
cookie, a currently authorized organization and a matching session context;
binding and clearing the pending session context commit atomically. Replays
cannot duplicate the purchase/provisioning intent. Return pending verification,
never a cluster, active license, credentials or an invented connection endpoint.

Test gates: all routes/methods/Host/TLS/Origin/form/cookie/CSRF validation;
real RSA-verified OIDC identity at callback, token failure and callback replay;
session rotation/logout/expiry/restart and pending-context substitution;
organization concurrent creation, rollback and revoked owner; cross-organization
read/bind denial and partial failures; actual loopback HTTP request cycles and
rendered HTML/assets. Fixture SDK/IdP responses must remain identified as such.
The separate real Casdoor protocol proof is not a browser end-to-end proof.

Before public deployment: real HTTPS IdP/client and provider login UI, verified
browser flow, reviewed session security, vetted WSGI/TLS/logging/rate limits,
operational provisioning/revocation/quotas/usage, live seller/buyer tests and
approved production budget remain required. /health/ready stays 503.

Primary sources checked 2026-10-29:

- https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html
- https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Set-Cookie

## Routes and configuration

| Method/path | Browser behavior |
| --- | --- |
| GET /account | Sign-in form or current organizations and scoped purchase states |
| GET /account/signin | Explicit sign-in/reauthentication form; no role/purchase mutation |
| POST /account/login | Exact Origin and prelogin CSRF, then fresh code/PKCE redirect |
| GET /account/callback | Single-use state, matching pending context, real signed ID-token verification and opaque session rotation |
| POST /account/organization | Session-bound CSRF, metadata-only personal workspace |
| POST /account/bind | Session-bound CSRF, fresh admin authorization, atomic pending binding/context clear |
| POST /account/logout | Durable local revocation; clear owned cookies |
| GET /account/style.css, /account/logo.png | Fixed local CSS and original Runix PNG only |
| POST /marketplace/register | Configured real resolver, opaque HttpOnly pending cookie, 303 /account and fresh login |

The standalone API keeps its original JSON handoff. The optional wrapper changes
only its explicitly listed browser paths; /api remains signed-Bearer-only and
/health/ready stays 503. New Marketplace registration clears the old browser
credentials so a current session without matching pending context cannot trap
the new purchase flow. It keeps the new pending claim through login, instead of
losing it during sign-out. Session revocation is checked inside the organization
mutation transaction and again before committing a purchase binding.

The existing loopback runner accepts an optional `browser` object in its fixed
operator JSON config. Required browser keys: client_id, authorization_endpoint,
token_endpoint, redirect_uri, jwks, client_secret_file. Issuer comes from the
existing verified control-plane config; callback must be exactly
public_origin/account/callback. No sample production identity/client is supplied.
The client secret is read from an absolute private regular file with O_NOFOLLOW,
private mode, bounded size and no inline secret. Config errors remain sanitized.
Production still needs a vetted WSGI/TLS setup; the development runner does not
trust X-Forwarded-* headers or expose a public socket. Shared HttpError lives in
a separate module so running the HTTP script as __main__ does not create a
second exception class with different handling in the browser wrapper.

## Local verification, 2026-10-29

Implemented control_plane_browser.py, control_plane_sessions.py, shared HTTP
errors, optional runner setup and create_personal_organization. Added 44 browser,
session and organization tests plus 2 OIDC context/migration tests. All **329
Python tests pass locally**, with provenance, compilation and whitespace checks.
Tests include real RSA callback verification and actual loopback TCP/WSGI cookie
round trips across registration, login, workspace creation, binding and logout.
Provider token HTTP and registration resolution in these unit tests are synthetic;
they are not a real buyer or actual browser/provider login proof.

Failure/race coverage includes cross-browser callback and pending-cookie swaps,
logout committed after initial authentication, expired/stopped claims, foreign
organizations, revoked/downgraded owners, duplicate binds, concurrent workspace
creation, real process exit/restart, transaction rollback of partial owner/session/
binding changes, unsafe secret files, duplicate cookies/forms, HTML escaping and
actual script entrypoint configuration. Unknown/forged session tokens and CSRF
values never authorize an operation. Raw session tokens, CSRF, claims, AWS tokens,
OAuth codes/access tokens and client secrets are absent from SQL dumps.

Actual in-app browser visual QA opened the logged-out page with original Runix
logo and local CSS. Screenshot (outside Git):
/Users/cuihuan/.codex/visualizations/2026/10/23/01a167ad-48e4-7ee0-b081-6812d6f6804b/runix-fs-browser-login-20261029.png
The first visual fixture reused a database pinned to another origin and correctly
returned a conflict. A fresh independent database rendered the sign-in page.
Both temporary HTTP servers were stopped and their listening ports checked empty;
this is not a persistent preview or usable production login address.

Re-ran the separate real cached-Casdoor code/S256 protocol smoke after adding the
state-context migration. Actual signed token, fresh-code/wrong-PKCE, redeemed-
code/correct-PKCE and callback replay checks passed, with owned-resource cleanup:
/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-oidc-smoke-2d5wo7t3/
This proves the actual provider protocol only. No browser was signed into that
provider, no production identity service was selected/configured, no AWS request
or resource creation was performed and no public Marketplace state was changed.
