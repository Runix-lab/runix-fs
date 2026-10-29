"""Real disposable-provider code/PKCE test; never print credential-bearing bytes."""
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlencode, urlsplit

from control_plane_oidc import CodeTokenClient, IdTokenVerifier, OidcFlow, OidcProvider, digest
from local_oidc_provider import IMAGE, provider
from marketplace_adapter import MarketplaceDenied
from marketplace_metering import MeteringOutbox


def now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def run():
    with provider() as fixture:
        metadata = json.loads((fixture.runtime / 'provider-metadata.json').read_text())
        if 'S256' not in metadata.get('code_challenge_methods_supported', []):
            raise RuntimeError('Actual provider does not advertise S256')
        config = OidcProvider(fixture.origin, fixture.client_id, metadata['authorization_endpoint'],
            metadata['token_endpoint'], fixture.redirect_uri, allow_loopback_testing=True)
        jwks_url = urlsplit(metadata['jwks_uri'])
        if (jwks_url.scheme, jwks_url.netloc) != ('http', '127.0.0.1:8000'):
            raise RuntimeError('Unexpected local public-key origin')
        status, _, body = fixture.request(metadata['jwks_uri'])
        if status != 200:
            raise RuntimeError('Local JWKS unavailable')
        jwks = json.loads(body)
        verifier = IdTokenVerifier(config, jwks)
        client = CodeTokenClient(config, fixture.client_secret, fixture.request)
        store = MeteringOutbox(fixture.runtime / 'login.db', '123456789012', 'synthetic-product')
        try:
            flow = OidcFlow(store, config, verifier, client)
            browser = secrets.token_urlsafe(32)
            start = flow.begin(browser, now())
            def issue_code(start):
                query = {key: value[0] for key, value in parse_qs(urlsplit(start.authorization_url).query).items()}
                # Official Casdoor form/auth.go and controllers/auth.go define this
                # synthetic credential-to-code step. It does not test browser UI.
                login_query = dict(clientId=query['client_id'], responseType='code', redirectUri=query['redirect_uri'],
                    scope=query['scope'], state=query['state'], nonce=query['nonce'],
                    code_challenge_method='S256', code_challenge=query['code_challenge'])
                form = dict(type='code', signinMethod='Password', organization=fixture.organization,
                    username=fixture.username, password=fixture.password, application=fixture.application)
                status, _, body = fixture.request(fixture.origin + '/api/login?' + urlencode(login_query),
                    data=json.dumps(form).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                response = json.loads(body)
                if status != 200 or response.get('status') != 'ok' or not isinstance(response.get('data'), str):
                    # Error text can contain secrets; report only category, never body.
                    raise RuntimeError('Synthetic provider authorization-code issuance failed')
                return response['data']
            wrong_start = flow.begin(browser, now())
            wrong_code = issue_code(wrong_start)
            try:
                client.exchange(wrong_code, secrets.token_urlsafe(32))
            except MarketplaceDenied:
                pass
            else:
                raise RuntimeError('Fresh code accepted wrong S256 verifier')
            code = issue_code(start)
            original_verifier = store.db.execute('SELECT verifier FROM oidc_states WHERE state=?',
                (digest(start.state),)).fetchone()[0]
            stamp = now()
            principal = flow.complete(start.state, browser, stamp, code=code, clock=now)
            if principal.issuer != fixture.origin or not principal.subject:
                raise RuntimeError('Verified principal missing')
            try:
                flow.complete(start.state, browser, now(), code=code, clock=now)
            except MarketplaceDenied:
                pass
            else:
                raise RuntimeError('Consumed callback was accepted')
            try:
                client.exchange(code, original_verifier)
            except MarketplaceDenied:
                pass
            else:
                raise RuntimeError('Redeemed code was accepted again')
            result = {'image': IMAGE, 'protocol': 'authorization_code', 'pkce': 'S256',
                      'real_id_token_signature_verified': True, 'callback_replay_denied': True,
                      'redeemed_code_denied': True, 'fresh_code_wrong_pkce_denied': True, 'key_count': len(verifier.keys),
                      'key_sizes': sorted(key.key_size for key in verifier.keys.values()),
                      'browser_ui_verified': False, 'production_identity_configured': False}
            (fixture.runtime / 'protocol-result.json').write_text(json.dumps(result, indent=2) + '\n')
        finally:
            store.db.close()
    print(json.dumps({'runtime': str(fixture.runtime), 'result': result, 'owned_resources_removed': True}))


if __name__ == '__main__':
    run()
