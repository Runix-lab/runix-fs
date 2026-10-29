"""RS256 RFC 9068 access-token verification against an operator-pinned JWKS.

No provider discovery, browser login, session issuance or network key fetching.
"""

import json
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from marketplace_adapter import MarketplaceDenied
from marketplace_metering import instant
from marketplace_registration import Principal, subject_id


DENIED = 'Access token denied'
SCOPE_ATOM = r'[\x21\x23-\x5b\x5d-\x7e]+'


def bounded_text(value, maximum=255):
    return (isinstance(value, str) and 0 < len(value) <= maximum
            and value.strip() == value and all(ord(char) >= 33 for char in value))


def load_public_keys(jwks):
    if not isinstance(jwks, dict) or set(jwks) != {'keys'}:
        raise ValueError('Pinned public JWKS required')
    try:
        encoded = json.dumps(jwks, allow_nan=False).encode('utf-8')
    except (TypeError, ValueError):
        raise ValueError('Invalid public JWKS') from None
    if len(encoded) > 65536 or not isinstance(jwks['keys'], list) or not 1 <= len(jwks['keys']) <= 8:
        raise ValueError('Bounded public key set required')
    keys = {}
    for raw in jwks['keys']:
        if (not isinstance(raw, dict) or not bounded_text(raw.get('kid'), 128)
                or raw.get('kid') in keys or raw.get('kty') != 'RSA'
                or raw.get('alg', 'RS256') != 'RS256' or raw.get('use', 'sig') != 'sig'
                or raw.get('key_ops', ['verify']) != ['verify']
                or any(field in raw for field in ('d', 'p', 'q', 'dp', 'dq', 'qi', 'oth', 'jku', 'x5u'))):
            raise ValueError('Ambiguous, private or unsupported public key')
        try:
            key = jwt.PyJWK.from_dict(raw, algorithm='RS256').key
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ValueError('Invalid RSA public key') from None
        if not isinstance(key, RSAPublicKey) or not 2048 <= key.key_size <= 4096:
            raise ValueError('RSA signing keys must be 2048..4096 bits')
        keys[raw['kid']] = key
    return keys


class AccessTokenVerifier:
    def __init__(self, issuer, audience, client_ids, jwks, required_scope='runix:fs'):
        if not isinstance(issuer, str) or len(issuer) > 2048:
            raise ValueError('Fixed HTTPS issuer required')
        parsed = urlsplit(issuer)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Fixed HTTPS issuer required')
        if (not bounded_text(audience) or not bounded_text(required_scope, 128)
                or not re.fullmatch(SCOPE_ATOM, required_scope)
                or not isinstance(client_ids, (list, tuple, set, frozenset))
                or not 1 <= len(client_ids) <= 16
                or not all(bounded_text(client) for client in client_ids)):
            raise ValueError('Fixed audience, client allowlist and scope required')
        keys = load_public_keys(jwks)
        self.issuer, self.audience = issuer, audience
        self.client_ids, self.required_scope = frozenset(client_ids), required_scope
        self.keys = keys

    def verify(self, token, now):
        """Use a trusted server clock; raw tokens never become log/error strings."""
        try:
            current = instant(now)
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise ValueError('Invalid token size')
            header = jwt.get_unverified_header(token)
            if (header.get('alg') != 'RS256'
                    or header.get('typ') not in {'at+jwt', 'application/at+jwt'}
                    or not bounded_text(header.get('kid'), 128)
                    or any(field in header for field in ('crit', 'jku', 'x5u', 'jwk', 'b64'))):
                raise ValueError('Unsupported access token header')
            key = self.keys.get(header['kid'])
            if key is None:
                raise ValueError('Unknown signer')
            payload = jwt.decode(
                token, key, algorithms=['RS256'], audience=self.audience, issuer=self.issuer,
                options={
                    'require': ['iss', 'aud', 'sub', 'client_id', 'jti', 'iat', 'exp'],
                    'strict_aud': True,
                    # Explicit temporal checks below share the trusted server clock
                    # with the registry; signature, issuer and audience stay enabled.
                    'verify_exp': False, 'verify_iat': False, 'verify_nbf': False,
                },
            )
            if (payload['iss'] != self.issuer or payload['aud'] != self.audience
                    or payload['client_id'] not in self.client_ids
                    or not bounded_text(payload['jti'])
                    or type(payload['iat']) is not int or type(payload['exp']) is not int
                    or not 0 <= payload['iat'] <= current < payload['exp']
                    or not 0 < payload['exp'] - payload['iat'] <= 3600):
                raise ValueError('Invalid access-token claims')
            if 'nbf' in payload and (type(payload['nbf']) is not int
                    or not 0 <= payload['nbf'] <= current or payload['nbf'] >= payload['exp']):
                raise ValueError('Token not yet usable')
            subject_id(payload['sub'])
            scope = payload.get('scope')
            if (not isinstance(scope, str) or len(scope) > 2048
                    or not re.fullmatch(SCOPE_ATOM + r'(?: ' + SCOPE_ATOM + r')*', scope)
                    or self.required_scope not in scope.split(' ')):
                raise ValueError('Required scope missing')
            return Principal(self.issuer, payload['sub'], datetime.fromtimestamp(
                min(payload['exp'], current + 900), timezone.utc))
        except (jwt.PyJWTError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            raise MarketplaceDenied(DENIED) from None
