# Control-plane access-token verification

Scope, 2026-10-28: replace caller-constructed Principal fixtures at the future
HTTP boundary with actual asymmetric JWT signature verification. This does not
provision an identity provider, register an OAuth client, implement browser SSO
or prove a deployed Runix login service exists.

Initial supported profile: RFC 9068 JWT access tokens, RS256 only, with at+jwt
type. Configure one HTTPS issuer, API audience, allowed client IDs and required
scope, plus a pinned public JWKS from the operator's verified provider. No
discovery/fetch from a token's jku/x5u/iss, no symmetric/none fallback, no ID-token
acceptance and no wildcard issuer/audience/client. Unknown kid or an unsupported
provider profile denies access; add an explicitly reviewed adapter rather than
silently relaxing this profile to match an unknown provider.

Use PyJWT and cryptography, not handwritten cryptographic verification. Bound
token/JWKS sizes; reject private JWK fields, ambiguous kid, non-RSA/non-signature
keys and keys outside 2048..4096 bits. Operator key replacement is explicit;
the verifier never downloads keys or silently trusts a new signer. JWT header
URLs/critical extensions are rejected. JWT signatures are verified before
claims become an authentication context.

Require iss/aud/sub/client_id/jti/iat/exp and the configured scope. Check exact
issuer and audience, client allowlist, nonempty subject, integer UTC NumericDate,
expiry, optional nbf and bounded token lifetime. Use a trusted server-supplied
clock for explicit temporal validation; token fields never choose the clock.
Require issued-at <= now, not-before <= now < expiry, and exp-iat <=3600 seconds.
Return Principal with expiry capped to min(token exp, now+15min); organization
roles still come from fresh registry membership reads, never JWT org/admin
claims. Authentication alone does not bind a purchase, allocate a cluster or
grant an active Marketplace license.

Every verification failure returns a generic denied error without raw token,
key or decoded identity data. Never log Authorization, registration POST bodies
or JWTs. Tests generate ephemeral signing keys in memory; no private keys or
real tokens are committed. Tests must use real signatures and cover forged,
tampered, wrong-key/issuer/audience/client/type/scope tokens, missing/expired or
future fields, algorithm confusion, malicious key URLs, malformed/oversized
inputs, kid/key rotation and verified identity -> live membership binding.

References checked 2026-10-28:

- https://www.rfc-editor.org/rfc/rfc9068.html
- https://pyjwt.readthedocs.io/en/stable/api.html
- https://pyjwt.readthedocs.io/en/stable/usage.html

Selected dependencies from official PyPI: PyJWT 2.15.1, cryptography 50.0.2.
Independent security review and actual provider/client configuration remain
requirements before production authentication or public fulfillment setup.

## Local verification

Implemented `scripts/runix/control_plane_auth.py`; 13 new tests pass and the
combined suite now has **131 passing tests**. Real ephemeral RSA signatures
exercise tampering, wrong signer, unsigned/HMAC confusion, key rotation,
identity/time/scope validation and signature-derived Principal -> durable
organization authorization. JWT organization/admin claims cannot override
database membership, and removing membership denies the next operation even
with a still-valid signed token. No actual identity-provider login occurred.

Two first-run fixture failures were corrected: the current signing library
refuses to create an HMAC token using a public asymmetric key and normalizes
certain protected headers while encoding. Adversarial test fixtures now sign
their exact malicious wire representation directly with ephemeral test keys;
production verification still uses PyJWT/cryptography. This validates the
rejected wire input rather than assuming the encoder preserved it.

Actual AWS CLI identity check still returns NoCredentials. No real seller API,
OAuth client registration, public service, paid resource or live token is used.
