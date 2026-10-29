# OIDC browser-login foundation and real local provider verification

Scope: implement the backend authorization-code/PKCE foundation and validate it
against a fresh pinned Casdoor test instance before adding the browser HTTP
session/organization UI. Existing RFC 9068 bearer verification stays separate;
ID tokens never become generic API bearer credentials. No production provider,
OAuth client, callback domain, credentials or shared Runix SSO is invented.

Source discovery, 2026-10-29: the actual Router console opens a username/password
sign-in. Its local deployment/branding repository is not the FS service and did
not establish an operator-approved OIDC issuer/client/JWKS or organization bridge.
Do not copy commercially licensed gateway code or reuse its cookies/API keys as
FS user identity. Existing gateway/Casdoor instances and dirty website source
remain untouched. The already cached official Casdoor image may be used in an
independent synthetic test container, with private state, an internal Docker
network and a client sharing only that fresh provider's loopback namespace.
No host port, cloud resource, download or paid identity service is needed.

Implementation contract: pin an HTTPS issuer, authorization/token endpoints,
client ID, redirect URI and public JWKS from the verified operator provider.
An explicit loopback-only local test exception must never permit a public HTTP
issuer/endpoint. Reject endpoint redirects, key URLs from tokens and requests
that choose a provider or outbound URL. Use authorization code plus S256 PKCE,
random state and nonce, browser correlation and a private durable single-use
state record. Commit consumption before token exchange; callback errors/replay,
expired or wrong browser state never obtain identity. Bound endpoint reads and
handle unavailable responses without leaking code, tokens or credentials.
The internal caller supplies a server-generated browser correlation secret;
the future HTTP wrapper must keep it in a secure HttpOnly cookie and enforce
browser-origin/CSRF rules. This backend alone does not implement that wrapper.
State lasts ten minutes; it is consumed with its PKCE verifier cleared before
network access. Expired rows are removed when a new login starts. Abandoned
rows are not automatically erased by a background job that does not yet exist.
Do not enclose callback completion in another database transaction. After a
lost/uncertain token response or process crash, restart login instead of
reusing an authorization code. Check the trusted clock again after exchange,
rejecting time regression, state expiry or an exchange taking 30 seconds.

Verify the actual ID token's RS256 signature with PyJWT/cryptography and pinned
public keys. Check exact issuer, client audience/authorized party, subject,
nonce and trusted clock, issued/expiry/not-before times and a bounded lifetime.
No provider org/admin claim overrides Runix DB membership. Do not accept ID tokens
through the existing access-token verifier or fabricate a login from a decoded
unsigned token. Keep session/provisioning readiness unclaimed until implemented.

Tests must include real signatures, tampered/wrong nonce/issuer/audience/key,
PKCE/state replay and wrong browser, callback concurrency, partial HTTP failure,
crash/restart, config pinning and credential redaction. A separate real provider
run must record protocol/claim/key metadata only, never passwords/cookies/tokens.
Clean up only owned fixture resources; keep all runtime data outside Git.

Primary references retrieved 2026-10-29:

- https://openid.net/specs/openid-connect-core-1_0.html
- https://www.rfc-editor.org/rfc/rfc9700.html
- https://casdoor.ai/docs/how-to-connect/oidc-client/
- https://casdoor.ai/docs/deployment/data-initialization/
- https://github.com/casdoor/casdoor/blob/master/form/auth.go
- https://github.com/casdoor/casdoor/blob/master/controllers/auth.go

Real browser HTTP handoff, session cookies/CSRF/logout, self-service organizations,
production IdP/client configuration, actual purchase/provisioning, independent
security review and public delivery remain required subsequent gates.

## Implemented local evidence, 2026-10-29

`control_plane_oidc.py` implements the internal begin/complete state machine,
fixed-endpoint confidential token exchange and separate ID-token verification.
Shared pinned RSA JWKS loading was extracted without changing the existing
RFC 9068 access-token acceptance profile. OIDC organization/admin claims do
not become Runix permissions. Config is pinned to the private SQLite database;
client secrets, authorization codes and tokens are never stored there.
An unconsumed PKCE verifier is sensitive runtime data in that private database.

`local_oidc_provider.py` and `local_oidc_smoke.py` use cached official Casdoor
digest `sha256:eb7a478c9d74494ebb5fd6ef3cfc7a6d40ea07d03bc24678bbd42fd3a9d00bdf`.
No existing service, login, real user or cloud resource is modified. The seed,
credentials, SQLite database and diagnostic logs remain outside the repository.
Only owned containers/network are removed, even after log-capture failures;
fresh resource inventories must confirm cleanup before a successful report.

Final actual protocol run:
`/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-oidc-smoke-1qb8plq4/`.
The actual provider issued a code for a synthetic user, enforced S256 on a
fresh code with a wrong verifier, exchanged a valid code and returned a signed
ID token verified against its actual 4096-bit RSA public key. Consumed callback
and redeemed code were refused. Cleanup was confirmed. This is real backend
HTTP protocol verification, not browser UI/session or production SSO proof.
Metadata/results contain no code, JWT, password, client secret or cookie.

Two initial host-published-loopback attempts failed to read the provider and
were cleaned up; those do not count as passes. The successful fixture shares
an isolated provider namespace instead and publishes no ports. A unit fixture
initially let PyJWT strip `b64=True`; exact-wire signing now verifies that this
unsupported header really is refused. Production verification uses PyJWT.

Verification: 30 new unit tests and the complete **283-test Python suite** pass
locally, together with provenance and Python compilation checks. No Rust engine
change. A consumed code was retried with its original correct PKCE verifier
and refused; the separate fresh-code negative case used a wrong verifier.
`cleanup-result.json` records zero owned containers/networks and removal of the
secret environment file after actual Docker inventory checks.
