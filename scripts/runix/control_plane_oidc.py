"""Pinned OIDC code/PKCE backend foundation; no browser routes or sessions yet."""
import base64
import hashlib
import hmac
import http.client
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import quote, urlencode, urlsplit

import jwt

from control_plane_auth import bounded_text, load_public_keys
from marketplace_adapter import MarketplaceDenied
from marketplace_metering import MeteringConflict, instant
from marketplace_registration import Principal, subject_id

DENIED = 'OIDC login denied'
UNAVAILABLE = 'OIDC provider unavailable'
SECRET = re.compile(r'[A-Za-z0-9_-]{43,128}')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def s256(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode('ascii')).digest()).rstrip(b'=').decode()


def fixed_url(value, local=False):
    if not bounded_text(value, 2048):
        raise ValueError('Fixed provider URL required')
    parsed = urlsplit(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or '\\' in value or parsed.port == 0
            or (parsed.scheme != 'https' and not (local and parsed.scheme == 'http'
                and parsed.hostname in {'127.0.0.1', '::1'}))):
        raise ValueError('HTTPS provider URL required')
    return parsed


@dataclass(frozen=True)
class OidcProvider:
    issuer: str
    client_id: str
    authorization_endpoint: str
    token_endpoint: str
    redirect_uri: str
    allow_loopback_testing: bool = False

    def __post_init__(self):
        if type(self.allow_loopback_testing) is not bool or not bounded_text(self.client_id):
            raise ValueError('Fixed OIDC client required')
        issuer = fixed_url(self.issuer, self.allow_loopback_testing)
        for endpoint in (self.authorization_endpoint, self.token_endpoint):
            parsed = fixed_url(endpoint, self.allow_loopback_testing)
            if (parsed.scheme, parsed.hostname, parsed.port) != (issuer.scheme, issuer.hostname, issuer.port):
                raise ValueError('Provider endpoints must share pinned issuer origin')
        fixed_url(self.redirect_uri, self.allow_loopback_testing)


class IdTokenVerifier:
    """OIDC ID tokens are accepted here only, never as API access tokens."""
    def __init__(self, provider, jwks):
        self.provider, self.keys = provider, load_public_keys(jwks)

    def verify(self, token, now, nonce_digest, *, code, access_token):
        try:
            stamp = instant(now)
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise ValueError()
            header = jwt.get_unverified_header(token)
            if (header.get('alg') != 'RS256' or header.get('typ') not in {None, 'JWT'}
                    or not bounded_text(header.get('kid'), 128)
                    or any(key in header for key in ('crit', 'jku', 'x5u', 'jwk', 'b64'))):
                raise ValueError()
            payload = jwt.decode(token, self.keys[header['kid']], algorithms=['RS256'],
                audience=self.provider.client_id, issuer=self.provider.issuer,
                options={'require': ['iss', 'sub', 'aud', 'iat', 'exp', 'nonce'],
                         'verify_exp': False, 'verify_iat': False, 'verify_nbf': False})
            audience = payload['aud']
            if isinstance(audience, str):
                audience = [audience]
            if (not isinstance(audience, list) or not 1 <= len(audience) <= 8
                    or not all(bounded_text(item) for item in audience)
                    or len(set(audience)) != len(audience)
                    or self.provider.client_id not in audience
                    or (len(audience) > 1 and payload.get('azp') != self.provider.client_id)
                    or ('azp' in payload and payload['azp'] != self.provider.client_id)
                    or payload['iss'] != self.provider.issuer
                    or type(payload['iat']) is not int or type(payload['exp']) is not int
                    or not 0 <= payload['iat'] <= stamp < payload['exp']
                    or not 0 < payload['exp'] - payload['iat'] <= 3600):
                raise ValueError()
            for key in ('nbf', 'auth_time'):
                if key in payload and (type(payload[key]) is not int or not 0 <= payload[key] <= stamp
                                       or payload[key] >= payload['exp']):
                    raise ValueError()
            subject_id(payload['sub'])
            if (not bounded_text(payload['nonce'], 128) or not isinstance(nonce_digest, str)
                    or not hmac.compare_digest(digest(payload['nonce']), nonce_digest)):
                raise ValueError()
            for key, value in (('c_hash', code), ('at_hash', access_token)):
                if key in payload:
                    expected = base64.urlsafe_b64encode(hashlib.sha256(value.encode('ascii')).digest()[:16]).rstrip(b'=').decode()
                    if not isinstance(payload[key], str) or not hmac.compare_digest(payload[key], expected):
                        raise ValueError()
            return Principal(self.provider.issuer, payload['sub'], datetime.fromtimestamp(
                min(payload['exp'], stamp + 900), timezone.utc))
        except (jwt.PyJWTError, KeyError, TypeError, ValueError, UnicodeError, OverflowError):
            raise MarketplaceDenied(DENIED) from None


def strict_json(body):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result
    if not isinstance(body, bytes) or len(body) > 65536:
        raise ValueError('Bounded JSON required')
    result = json.loads(body, object_pairs_hook=pairs,
                        parse_constant=lambda value: (_ for _ in ()).throw(ValueError()))
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    return result


def endpoint_request(url, *, data, headers, method):
    """Fixed operator URL only. Direct verified TLS, bounded read, no redirects/proxy."""
    parsed = urlsplit(url)
    cls = http.client.HTTPSConnection if parsed.scheme == 'https' else http.client.HTTPConnection
    connection = cls(parsed.hostname, parsed.port, timeout=5)
    try:
        connection.request(method, parsed.path or '/', body=data, headers=headers)
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError('Oversized response')
        return response.status, dict(response.getheaders()), body
    finally:
        connection.close()


class CodeTokenClient:
    def __init__(self, provider, client_secret, request=endpoint_request):
        if not bounded_text(client_secret, 4096):
            raise ValueError('Confidential client secret required')
        self.provider, self._secret, self.request = provider, client_secret, request

    def exchange(self, code, verifier):
        try:
            if (not bounded_text(code, 4096) or not SECRET.fullmatch(verifier)):
                raise ValueError()
            basic = base64.b64encode((quote(self.provider.client_id, safe='') + ':'
                + quote(self._secret, safe='')).encode()).decode()
            data = urlencode({'grant_type': 'authorization_code', 'code': code,
                              'client_id': self.provider.client_id,
                              'redirect_uri': self.provider.redirect_uri, 'code_verifier': verifier}).encode()
            status, headers, body = self.request(self.provider.token_endpoint, data=data,
                headers={'Authorization': 'Basic ' + basic, 'Content-Type': 'application/x-www-form-urlencoded',
                         'Accept': 'application/json'}, method='POST')
            if status != 200:
                raise ValueError()
            payload = strict_json(body)
            if (not bounded_text(payload.get('id_token'), 16384)
                    or not bounded_text(payload.get('access_token'), 16384)
                    or not isinstance(payload.get('token_type'), str)
                    or payload['token_type'].lower() != 'bearer' or 'error' in payload):
                raise ValueError()
            return payload['id_token'], payload['access_token']
        except Exception:
            # Includes transport failures; codes, tokens and response bodies stay private.
            raise MarketplaceDenied(UNAVAILABLE) from None


@dataclass(frozen=True)
class LoginStart:
    authorization_url: str = field(repr=False)
    state: str = field(repr=False)


class OidcFlow:
    """Internal backend API. Caller must supply a secure browser correlation secret.

    No HTTP route/session/organization is created. Never wrap complete() in an
    outer DB transaction: consumption must commit before the network operation.
    """
    def __init__(self, store, provider, verifier, token_client):
        if verifier.provider != provider or token_client.provider != provider:
            raise ValueError('OIDC components must share pinned configuration')
        self.store, self.provider, self.verifier, self.token_client = store, provider, verifier, token_client
        config = json.dumps(provider.__dict__, sort_keys=True)
        with store.transaction():
            store.db.execute('CREATE TABLE IF NOT EXISTS oidc_settings (id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL)')
            store.db.execute('INSERT OR IGNORE INTO oidc_settings VALUES(1,?)', (config,))
            if store.db.execute('SELECT config FROM oidc_settings WHERE id=1').fetchone()[0] != config:
                raise MeteringConflict('OIDC database configuration mismatch')
            store.db.execute('''CREATE TABLE IF NOT EXISTS oidc_states (
                state TEXT PRIMARY KEY, browser TEXT NOT NULL, verifier TEXT,
                nonce TEXT NOT NULL, issued INTEGER NOT NULL, expires INTEGER NOT NULL,
                consumed INTEGER)''')

    def begin(self, browser_secret, now):
        if not isinstance(browser_secret, str) or not SECRET.fullmatch(browser_secret):
            raise MarketplaceDenied(DENIED)
        stamp = instant(now)
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        with self.store.transaction():
            # Bound credential lifetime on disk, also after abandoned sign-ins.
            self.store.db.execute('DELETE FROM oidc_states WHERE expires<=?', (stamp,))
            self.store.db.execute('INSERT INTO oidc_states VALUES(?,?,?,?,?,?,NULL)',
                (digest(state), digest(browser_secret), verifier, digest(nonce), stamp, stamp + 600))
        query = urlencode({'response_type': 'code', 'client_id': self.provider.client_id,
            'redirect_uri': self.provider.redirect_uri, 'scope': 'openid', 'state': state,
            'nonce': nonce, 'code_challenge': s256(verifier), 'code_challenge_method': 'S256'})
        return LoginStart(self.provider.authorization_endpoint + '?' + query, state)

    def complete(self, state, browser_secret, now, *, code=None, error=None, clock=None):
        if self.store.db.in_transaction:
            raise RuntimeError('OIDC callback requires an independent transaction')
        if (not isinstance(state, str) or not SECRET.fullmatch(state)
                or not isinstance(browser_secret, str) or not SECRET.fullmatch(browser_secret)):
            raise MarketplaceDenied(DENIED)
        stamp = instant(now)
        with self.store.transaction():
            row = self.store.db.execute('SELECT * FROM oidc_states WHERE state=?', (digest(state),)).fetchone()
            if (not row or not hmac.compare_digest(row['browser'], digest(browser_secret))
                    or row['consumed'] is not None or not row['issued'] <= stamp < row['expires']):
                raise MarketplaceDenied(DENIED)
            verifier, nonce, expires = row['verifier'], row['nonce'], row['expires']
            self.store.db.execute('UPDATE oidc_states SET consumed=?,verifier=NULL WHERE state=?', (stamp, digest(state)))
        # Any callback after matching state is terminal, including provider error
        # or ambiguous code. A lost/uncertain exchange starts a new login instead.
        if error is not None or not bounded_text(code, 4096):
            raise MarketplaceDenied(DENIED)
        token, access_token = self.token_client.exchange(code, verifier)
        current = clock() if clock is not None else datetime.now(timezone.utc).replace(microsecond=0)
        if not stamp <= instant(current) < min(expires, stamp + 30):
            raise MarketplaceDenied(DENIED)
        return self.verifier.verify(token, current, nonce, code=code, access_token=access_token)
