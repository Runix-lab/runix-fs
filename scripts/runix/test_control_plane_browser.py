"""Local WSGI/browser boundary with real signatures and synthetic IdP/AWS I/O."""
import dataclasses
import http.client
import io
import json
import os
import runpy
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import Mock, patch
from wsgiref.simple_server import WSGIServer
from wsgiref.util import setup_testing_defaults

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from control_plane_auth import AccessTokenVerifier
from control_plane_browser import BrowserAccountApp, from_config
from control_plane_http import ControlPlaneApp, QuietRequestHandler
from control_plane_oidc import CodeTokenClient, IdTokenVerifier, OidcFlow, OidcProvider, digest
from control_plane_sessions import BrowserSessions
from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase, RegistrationGateway
from marketplace_metering import MeteringConflict, MeteringOutbox
from marketplace_registration import Principal, RegistrationRegistry

NOW = datetime(2026, 10, 29, 10, tzinfo=timezone.utc)
ISSUER, ORIGIN = 'https://identity.example.test', 'https://account.example.test'
SELLER, PRODUCT = '999999999999', 'synthetic-product'
CONFIG = OidcProvider(ISSUER, 'browser-test', ISSUER + '/authorize', ISSUER + '/token', ORIGIN + '/account/callback')
PURCHASE = Purchase('123456789012', 'arn:aws:license-manager:us-east-1:999999999999:license:browser-test', PRODUCT, 'agmt-browser-test')


class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(RSAAlgorithm.to_jwk(cls.private.public_key()))
        public.update(kid='browser-key', alg='RS256', use='sig')
        cls.jwks = {'keys': [public]}
        cls.access_verifier = AccessTokenVerifier(ISSUER, 'runix-fs-api', ['browser-test'], cls.jwks)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'browser.db')
        self.gateway = Mock(spec=RegistrationGateway, seller_account=SELLER, product_code=PRODUCT)
        self.gateway.resolve_registration.return_value = PURCHASE
        self.api = ControlPlaneApp(self.path, SELLER, PRODUCT, self.access_verifier, ORIGIN, self.gateway)
        self.transport = Mock()
        self.client = CodeTokenClient(CONFIG, 'synthetic-client-secret', self.transport)
        self.current = NOW
        self.app = BrowserAccountApp(self.api, CONFIG, self.jwks, self.client, clock=lambda: self.current)
        self.cookies = {}
        self.box = MeteringOutbox(self.path, SELLER, PRODUCT)
        self.addCleanup(self.box.close)
        self.registry = RegistrationRegistry(self.box, self.gateway, ISSUER)
        self.sessions = BrowserSessions(self.box, ISSUER, ORIGIN)

    def request(self, path='/account', method='GET', fields=None, *, origin=ORIGIN, cookie=None, body=None, **overrides):
        environ = {}
        setup_testing_defaults(environ)
        route, _, query = path.partition('?')
        if body is None:
            body = urlencode(fields or {}).encode()
        environ.update(PATH_INFO=route, QUERY_STRING=query, REQUEST_METHOD=method,
            HTTP_HOST='account.example.test', REMOTE_ADDR='127.0.0.1', CONTENT_TYPE='application/x-www-form-urlencoded',
            CONTENT_LENGTH=str(len(body)), HTTP_COOKIE=cookie if cookie is not None else '; '.join(k + '=' + v for k, v in self.cookies.items()),
            **{'wsgi.url_scheme': 'https', 'wsgi.input': io.BytesIO(body)})
        if origin is not None:
            environ['HTTP_ORIGIN'] = origin
        environ.update(overrides)
        result = {}
        def start(status, headers):
            result.update(status=int(status.split(' ')[0]), headers=headers)
            for key, value in headers:
                if key == 'Set-Cookie':
                    jar = SimpleCookie(value)
                    for name, morsel in jar.items():
                        if morsel['max-age'] == '0':
                            self.cookies.pop(name, None)
                        else:
                            self.cookies[name] = morsel.value
        result['body'] = b''.join(self.app(environ, start))
        result['location'] = next((v for k, v in result['headers'] if k == 'Location'), None)
        return result

    def key(self, key):
        return self.app.prefix + key

    def begin_login(self):
        response = self.request('/account/signin')
        self.assertEqual(response['status'], 200)
        csrf = self.cookies[self.key('prelogin')]
        response = self.request('/account/login', 'POST', {'csrf': csrf})
        self.assertEqual(response['status'], 303)
        return {key: value[0] for key, value in parse_qs(urlsplit(response['location']).query).items()}

    def callback(self, query, subject='browser-user', changes=None):
        payload = dict(iss=ISSUER, aud=CONFIG.client_id, sub=subject, nonce=query['nonce'],
            iat=int(self.current.timestamp()), exp=int(self.current.timestamp()) + 600,
            isAdmin=True, organization='foreign-admin-org')
        payload.update(changes or {})
        token = jwt.encode(payload, self.private, algorithm='RS256', headers={'typ': 'JWT', 'kid': 'browser-key'})
        self.transport.return_value = (200, {}, json.dumps(dict(id_token=token, access_token='synthetic-access', token_type='Bearer')).encode())
        return self.request('/account/callback?' + urlencode({'state': query['state'], 'code': 'synthetic-code'}))

    def login(self, subject='browser-user'):
        query = self.begin_login()
        response = self.callback(query, subject)
        self.assertEqual(response['status'], 303)
        self.assertEqual(response['location'], '/account')
        return query

    def post(self, path, **fields):
        return self.request(path, 'POST', dict(csrf=self.cookies[self.key('csrf')], **fields))

    def register(self):
        result = self.request('/marketplace/register', 'POST', {'x-amzn-marketplace-token': 'synthetic-aws-token'}, origin='https://aws.amazon.com')
        self.assertEqual(result['status'], 303)
        self.assertEqual(result['location'], '/account')
        return self.cookies[self.key('pending')]

    def create_org(self):
        result = self.post('/account/organization')
        self.assertEqual(result['status'], 303)
        return parse_qs(urlsplit(result['location']).query)['organization_id'][0]

    def test_login_page_and_fixed_original_assets(self):
        result = self.request()
        self.assertIn(b'Continue to sign in', result['body'])
        self.assertNotIn(b'synthetic-client-secret', result['body'])
        headers = dict(result['headers'])
        self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(headers['Strict-Transport-Security'], 'max-age=31536000')
        css = self.request('/account/style.css')
        self.assertEqual(css['status'], 200)
        self.assertIn(b'@media', css['body'])
        logo = self.request('/account/logo.png')
        self.assertTrue(logo['body'].startswith(b'\x89PNG'))
        self.assertEqual(self.request('/account/../../LICENSE')['status'], 404)

    def test_real_signature_callback_creates_session_only(self):
        self.login()
        self.assertEqual(self.request()['status'], 200)
        self.assertIn(b'Create my organization', self.request()['body'])
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM org_memberships').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0], 0)
        for name, value in self.cookies.items():
            self.assertTrue(name.startswith('__Host-'))
            self.assertEqual(len(value), 43)
        self.assertEqual(self.request('/health/ready')['status'], 503)

    def test_secure_cookie_flags_no_domain_and_callback_no_code_in_redirect(self):
        query = self.begin_login()
        result = self.callback(query)
        for key, value in result['headers']:
            if key == 'Set-Cookie':
                for required in ('Secure', 'HttpOnly', 'Path=/', 'SameSite=Lax'):
                    self.assertIn(required, value)
                self.assertNotIn('Domain=', value)
        self.assertNotIn('synthetic-code', result['location'])
        self.assertNotIn(b'synthetic-code', result['body'])

    def test_full_pending_handoff_organization_binding_and_fresh_reads(self):
        claim = self.register()
        self.login()
        org = self.create_org()
        page = self.request('/account?' + urlencode({'organization_id': org}))
        self.assertIn(b'Bind subscription', page['body'])
        self.assertNotIn(claim.encode(), page['body'])
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 303)
        self.assertNotIn(self.key('pending'), self.cookies)
        page = self.request('/account?' + urlencode({'organization_id': org}))
        self.assertIn(b'pending_license_verification', page['body'])
        self.assertNotIn(b'Bind subscription', page['body'])
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT pending FROM browser_sessions WHERE revoked IS NULL').fetchone()[0], None)
        self.assertEqual(self.request('/health/ready')['status'], 503)

    def test_cookie_credentials_never_authenticate_bearer_api(self):
        self.login()
        self.assertEqual(self.request('/api/fs/organizations')['status'], 401)
        result = self.request('/account', HTTP_AUTHORIZATION='Bearer ignored')
        self.assertEqual(result['status'], 400)

    def test_all_browser_mutations_require_exact_origin(self):
        self.login()
        for path in ('/account/login', '/account/logout', '/account/organization', '/account/bind'):
            for origin in (None, 'null', 'https://evil.test', 'https://account.example.test.evil.test'):
                with self.subTest(path=path, origin=origin):
                    self.assertEqual(self.request(path, 'POST', {'csrf': 'x'}, origin=origin)['status'], 403)
        self.assertEqual(self.request('/account/logout', 'POST', {'csrf': self.cookies[self.key('csrf')]}, HTTP_SEC_FETCH_SITE='same-site')['status'], 403)

    def test_login_cookie_form_match_and_post_csrf_required(self):
        self.request()
        for token in ('bad', secrets.token_urlsafe(32)):
            self.assertEqual(self.request('/account/login', 'POST', {'csrf': token})['status'], 403)
        self.transport.assert_not_called()
        self.login()
        for path in ('/account/logout', '/account/organization'):
            for fields in ({}, {'csrf': 'bad'}, {'csrf': secrets.token_urlsafe(32)}):
                self.assertIn(self.request(path, 'POST', fields)['status'], (400, 403))
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM personal_organizations').fetchone()[0], 0)

    def test_pending_substitution_removal_or_insertion_across_login_denied(self):
        for original in (None, secrets.token_urlsafe(32)):
            for replacement in (None, secrets.token_urlsafe(32)):
                if original == replacement:
                    continue
                self.cookies.clear()
                if original:
                    self.cookies[self.key('pending')] = original
                query = self.begin_login()
                if replacement:
                    self.cookies[self.key('pending')] = replacement
                else:
                    self.cookies.pop(self.key('pending'), None)
                before = self.transport.call_count
                self.assertEqual(self.callback(query)['status'], 403)
                self.assertEqual(self.transport.call_count, before)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM browser_sessions').fetchone()[0], 0)

    def test_callback_nonce_issuer_audience_and_signature_profiles_fail_closed(self):
        for changes in ({'nonce': 'wrong'}, {'iss': ISSUER + '/other'}, {'aud': 'other'}, {'exp': int(NOW.timestamp())}):
            query = self.begin_login()
            self.assertEqual(self.callback(query, changes=changes)['status'], 403)
            self.assertNotIn(self.key('session'), self.cookies)

    def test_callback_cross_browser_and_replay_deny(self):
        query = self.begin_login()
        original = self.cookies[self.key('correlation')]
        self.cookies[self.key('correlation')] = secrets.token_urlsafe(32)
        self.assertEqual(self.callback(query)['status'], 403)
        self.transport.assert_not_called()
        self.cookies[self.key('correlation')] = original
        self.assertEqual(self.callback(query)['status'], 303)
        self.cookies[self.key('correlation')] = original
        self.assertEqual(self.callback(query)['status'], 403)
        self.assertEqual(self.transport.call_count, 1)

    def test_callback_errors_and_failed_transport_never_echo_sensitive_data(self):
        query = self.begin_login()
        result = self.request('/account/callback?' + urlencode(dict(state=query['state'], error='sensitive-secret-error', error_description='sensitive-secret-description')))
        self.assertEqual(result['status'], 403)
        self.assertNotIn(b'sensitive-secret', result['body'])
        self.transport.assert_not_called()
        query = self.begin_login()
        self.transport.side_effect = OSError('sensitive-secret-token')
        result = self.callback(query)
        self.assertEqual(result['status'], 403)
        self.assertNotIn(b'sensitive-secret', result['body'])
        self.assertNotIn(self.key('session'), self.cookies)

    def test_login_rotates_and_revokes_previous_session(self):
        self.login()
        old = self.cookies[self.key('session')]
        self.login()
        self.assertNotEqual(self.cookies[self.key('session')], old)
        with self.assertRaises(MarketplaceDenied):
            self.sessions.authenticate(old, NOW)

    def test_logout_revocation_survives_reopen(self):
        self.login()
        old = self.cookies[self.key('session')]
        self.assertEqual(self.post('/account/logout')['status'], 303)
        self.assertEqual(self.cookies, {})
        reopened = MeteringOutbox(self.path, SELLER, PRODUCT)
        try:
            with self.assertRaises(MarketplaceDenied):
                BrowserSessions(reopened, ISSUER, ORIGIN).authenticate(old, NOW)
        finally:
            reopened.close()
        self.assertIn(b'Continue to sign in', self.request()['body'])

    def test_session_expiry_and_clock_regression_do_not_authenticate(self):
        self.login()
        for current in (NOW + timedelta(seconds=600), NOW - timedelta(seconds=1)):
            self.current = current
            self.assertIn(b'Continue to sign in', self.request()['body'])
        self.assertEqual(self.request('/account/logout', 'POST', {'csrf': self.cookies[self.key('csrf')]})['status'], 403)

    def test_new_marketplace_callback_forces_fresh_login_keeps_pending(self):
        self.login()
        old = self.cookies[self.key('session')]
        self.register()
        self.assertNotIn(self.key('session'), self.cookies)
        self.assertIn(self.key('pending'), self.cookies)
        self.assertIn(b'Continue to sign in', self.request()['body'])
        with self.assertRaises(MarketplaceDenied):
            self.sessions.authenticate(old, NOW)

    def test_cross_org_reads_and_bind_rejected_even_for_valid_session(self):
        self.register()
        self.login()
        self.registry.set_membership('foreign-org', 'another-subject', 'owner')
        self.assertEqual(self.request('/account?organization_id=foreign-org')['status'], 403)
        self.assertEqual(self.post('/account/bind', organization_id='foreign-org')['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM org_purchases').fetchone()[0], 0)

    def test_member_cannot_bind_and_revocation_is_fresh(self):
        self.register()
        self.login()
        self.registry.set_membership('test-org', 'browser-user', 'member')
        self.assertNotIn(b'Bind subscription', self.request('/account?organization_id=test-org')['body'])
        self.assertEqual(self.post('/account/bind', organization_id='test-org')['status'], 403)
        self.registry.set_membership('test-org', 'browser-user', None)
        self.assertEqual(self.request('/account?organization_id=test-org')['status'], 403)

    def test_bind_clearing_failure_rolls_back_purchase_and_intent(self):
        claim = self.register()
        self.login()
        org = self.create_org()
        self.box.db.execute("CREATE TRIGGER fail_clear BEFORE UPDATE ON browser_sessions WHEN NEW.pending IS NULL AND OLD.pending IS NOT NULL BEGIN SELECT RAISE(ABORT,'synthetic abort'); END")
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 503)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM org_purchases').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0], 0)
        self.assertEqual(self.cookies[self.key('pending')], claim)
        self.box.db.execute('DROP TRIGGER fail_clear')
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 303)
        self.cookies[self.key('pending')] = claim
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0], 1)

    def test_logout_committed_after_initial_auth_denies_org_creation(self):
        self.login()
        original = BrowserSessions.authorize_post
        once = []
        def raced(sessions, *args):
            result = original(sessions, *args)
            if not once:
                once.append(True)
                self.sessions.revoke(self.cookies[self.key('session')], NOW)
            return result
        with patch.object(BrowserSessions, 'authorize_post', raced):
            self.assertEqual(self.post('/account/organization')['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM personal_organizations').fetchone()[0], 0)

    def test_logout_committed_after_initial_auth_rolls_back_binding(self):
        self.register()
        self.login()
        org = self.create_org()
        original = BrowserSessions.authorize_post
        def raced(sessions, *args):
            result = original(sessions, *args)
            self.sessions.revoke(self.cookies[self.key('session')], NOW)
            return result
        with patch.object(BrowserSessions, 'authorize_post', raced):
            self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM org_purchases').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0], 0)

    def test_claim_expiry_and_cancelled_license_refuse_bind(self):
        claim = self.register()
        self.login()
        org = self.create_org()
        self.box.db.execute('UPDATE registration_claims SET expires=?', (int(NOW.timestamp()),))
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 403)
        self.box.db.execute('UPDATE registration_claims SET expires=?', (int(NOW.timestamp()) + 600,))
        self.box.db.execute('INSERT INTO license_stops VALUES(?,?,?,?)', (PURCHASE.license_arn, PURCHASE.account_id, PURCHASE.agreement_id, int(NOW.timestamp())))
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM org_purchases').fetchone()[0], 0)

    def test_registration_unavailable_and_invalid_forms_do_not_issue_cookie(self):
        self.gateway.resolve_registration.side_effect = MarketplaceUnavailable('secret-sdk-data')
        result = self.request('/marketplace/register', 'POST', {'x-amzn-marketplace-token': 'secret-aws'})
        self.assertEqual(result['status'], 503)
        self.assertNotIn(b'secret-', result['body'])
        self.assertNotIn(self.key('pending'), self.cookies)
        for body in (b'', b'x-amzn-marketplace-token=a&x-amzn-marketplace-token=b', b'x-amzn-marketplace-token=a&account=other'):
            self.assertEqual(self.request('/marketplace/register', 'POST', body=body)['status'], 400)

    def test_database_contains_no_raw_browser_tokens_claims_or_credentials(self):
        claim = self.register()
        self.login()
        dumped = '\n'.join(self.box.db.iterdump())
        for secret in [claim, 'synthetic-aws-token', 'synthetic-client-secret', 'synthetic-code', 'synthetic-access', *self.cookies.values()]:
            self.assertNotIn(secret, dumped)

    def test_validation_methods_forms_cookies_and_no_request_selected_urls(self):
        for path, method in self.app.ROUTES.items():
            with self.subTest(path=path):
                self.assertEqual(self.request(path, 'POST' if method == 'GET' else 'GET')['status'], 405)
        for cookie in (self.key('session') + '=bad', self.key('pending') + '=a',
                       self.key('session') + '=' + 'a' * 43 + '; ' + self.key('session') + '=' + 'b' * 43):
            self.assertEqual(self.request(cookie=cookie)['status'], 400)
        for path in ('/account?return_to=https://evil.test', '/account?organization_id=a&organization_id=b',
                     '/account/callback?state=a&state=b&code=c', '/account/callback?state=a&code=c&error=x',
                     '/account/callback?state=a&code=c&iss=https://evil.test', '/account/style.css?x=1'):
            self.assertEqual(self.request(path)['status'], 400)
        self.assertEqual(self.request('/account/login', 'POST', body=b'csrf=a&csrf=b')['status'], 400)
        self.assertEqual(self.request('/account/login', 'POST', body=b'x' * 8193)['status'], 413)

    def test_host_tls_peer_and_forwarded_headers_remain_strict(self):
        self.assertEqual(self.request(HTTP_HOST='evil.test')['status'], 421)
        self.assertEqual(self.request(**{'wsgi.url_scheme': 'http', 'HTTP_X_FORWARDED_PROTO': 'https'})['status'], 426)
        self.assertEqual(self.request('/account/login', 'POST', {'csrf': 'bad'}, CONTENT_TYPE='application/json')['status'], 415)

    def test_identity_and_callback_configuration_must_match(self):
        for config in (dataclasses.replace(CONFIG, issuer=ISSUER + '/different'),
                       dataclasses.replace(CONFIG, redirect_uri=ORIGIN + '/different')):
            with self.assertRaises(ValueError):
                BrowserAccountApp(self.api, config, self.jwks, CodeTokenClient(config, 'secret'))
        with self.assertRaises(MeteringConflict):
            BrowserSessions(self.box, ISSUER, 'https://other.example.test')
        with self.assertRaises(ValueError):
            BrowserSessions(self.box, 'http://identity.example.test', ORIGIN)

    def test_operator_config_private_secret_file_and_fixed_issuer(self):
        path = Path(self.directory.name) / 'client.secret'
        path.write_text('synthetic-secret-file\n')
        path.chmod(0o600)
        config = dict(client_id=CONFIG.client_id, authorization_endpoint=CONFIG.authorization_endpoint,
            token_endpoint=CONFIG.token_endpoint, redirect_uri=CONFIG.redirect_uri, jwks=self.jwks,
            client_secret_file=str(path))
        configured = from_config(self.api, config)
        self.assertEqual(configured.provider, CONFIG)
        for mode in (0o644, 0o666):
            path.chmod(mode)
            with self.assertRaises(ValueError):
                from_config(self.api, config)
        path.chmod(0o600)
        path.write_text('x' * 4097)
        with self.assertRaises(ValueError):
            from_config(self.api, config)
        path.write_text('valid-secret')
        symlink = Path(self.directory.name) / 'link.secret'
        symlink.symlink_to(path)
        with self.assertRaises(OSError):
            from_config(self.api, dict(config, client_secret_file=str(symlink)))
        for changes in ({'client_secret': 'inline-secret'}, {'client_secret_file': 'relative.secret'},
                        {'token_endpoint': 'https://evil.test/token'}):
            with self.assertRaises(ValueError):
                from_config(self.api, dict(config, **changes))

    def test_actual_script_entrypoint_loads_optional_browser_without_error_class_split(self):
        secret = Path(self.directory.name) / 'entry.secret'
        secret.write_text('synthetic-entry-secret')
        secret.chmod(0o600)
        browser = dict(client_id=CONFIG.client_id, authorization_endpoint=CONFIG.authorization_endpoint,
            token_endpoint=CONFIG.token_endpoint, redirect_uri=CONFIG.redirect_uri, jwks=self.jwks,
            client_secret_file=str(secret))
        config = dict(database=self.path, seller_account=SELLER, product_code=PRODUCT, issuer=ISSUER,
            audience='runix-fs-api', client_ids=['browser-test'], jwks=self.jwks, public_origin=ORIGIN,
            browser=browser)
        path = Path(self.directory.name) / 'control.json'
        path.write_text(json.dumps(config))
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        with patch('sys.argv', ['control_plane_http.py', '--config', str(path)]), \
                patch.object(RegistrationGateway, 'from_session', return_value=self.gateway), \
                patch('boto3.Session'), patch('wsgiref.simple_server.make_server', return_value=server) as factory, \
                patch('sys.stdout', new_callable=io.StringIO) as output:
            runpy.run_path(str(Path(__file__).parent / 'control_plane_http.py'), run_name='__main__')
        self.assertNotIn('synthetic-entry-secret', output.getvalue())
        app = factory.call_args.args[2]
        self.assertIsInstance(app, BrowserAccountApp)
        environ = {}
        setup_testing_defaults(environ)
        environ.update(PATH_INFO='/account', REQUEST_METHOD='GET', HTTP_HOST='evil.test')
        statuses = []
        b''.join(app(environ, lambda status, headers: statuses.append(status)))
        self.assertTrue(statuses[0].startswith('421 '))
        server.serve_forever.assert_called_once()

    def test_rendered_purchase_text_is_escaped(self):
        self.gateway.resolve_registration.return_value = dataclasses.replace(PURCHASE, agreement_id='<script>alert(1)</script>')
        self.register()
        self.login()
        org = self.create_org()
        self.assertEqual(self.post('/account/bind', organization_id=org)['status'], 303)
        page = self.request('/account?organization_id=' + org)['body']
        self.assertNotIn(b'<script>', page)
        self.assertIn(b'&lt;script&gt;', page)

    def test_real_loopback_http_login_create_bind_and_logout_cycles(self):
        # Actual TCP/WSGI and cookie round trips; provider/registration I/O is
        # deliberately synthetic, with a real RSA signature at the callback.
        server = WSGIServer(('127.0.0.1', 0), QuietRequestHandler)
        origin = 'http://127.0.0.1:' + str(server.server_port)
        config = dataclasses.replace(CONFIG, redirect_uri=origin + '/account/callback', allow_loopback_testing=True)
        api = ControlPlaneApp(self.path, SELLER, PRODUCT, self.access_verifier, origin, self.gateway)
        # Use a fresh DB because origin is immutable.
        api.database = str(Path(self.directory.name) / 'tcp.db')
        transport = Mock()
        app = BrowserAccountApp(api, config, self.jwks, CodeTokenClient(config, 'secret', transport), clock=lambda: NOW)
        server.set_app(app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        jar = {}
        def request(path, method='GET', fields=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                connection.request(method, path, body=urlencode(fields or {}), headers={'Origin': origin,
                    'Content-Type': 'application/x-www-form-urlencoded', 'Cookie': '; '.join(k + '=' + v for k, v in jar.items())})
                response = connection.getresponse()
                body, headers = response.read(), response.getheaders()
                for key, value in headers:
                    if key.lower() == 'set-cookie':
                        for name, morsel in SimpleCookie(value).items():
                            if morsel['max-age'] == '0':
                                jar.pop(name, None)
                            else:
                                jar[name] = morsel.value
                return response.status, dict(headers), body
            finally:
                connection.close()
        try:
            self.assertEqual(request('/marketplace/register', 'POST', {'x-amzn-marketplace-token': 'synthetic-aws'})[0], 303)
            self.assertEqual(request('/account')[0], 200)
            status, headers, _ = request('/account/login', 'POST', {'csrf': jar[app.prefix + 'prelogin']})
            self.assertEqual(status, 303)
            query = parse_qs(urlsplit(headers['Location']).query)
            payload = dict(iss=ISSUER, aud=CONFIG.client_id, sub='tcp-user', nonce=query['nonce'][0],
                iat=int(NOW.timestamp()), exp=int(NOW.timestamp()) + 600)
            token = jwt.encode(payload, self.private, algorithm='RS256', headers={'kid': 'browser-key', 'typ': 'JWT'})
            transport.return_value = (200, {}, json.dumps(dict(id_token=token, access_token='synthetic', token_type='Bearer')).encode())
            self.assertEqual(request('/account/callback?' + urlencode(dict(state=query['state'][0], code='synthetic')))[0], 303)
            self.assertEqual(request('/api/fs/organizations')[0], 401)
            csrf = jar[app.prefix + 'csrf']
            status, headers, _ = request('/account/organization', 'POST', {'csrf': csrf})
            self.assertEqual(status, 303)
            org = parse_qs(urlsplit(headers['Location']).query)['organization_id'][0]
            self.assertIn(b'Bind subscription', request(headers['Location'])[2])
            self.assertEqual(request('/account/bind', 'POST', {'csrf': csrf, 'organization_id': org})[0], 303)
            self.assertIn(b'pending_license_verification', request('/account?organization_id=' + org)[2])
            self.assertEqual(request('/account/logout', 'POST', {'csrf': csrf})[0], 303)
            self.assertIn(b'Continue to sign in', request('/account')[2])
            self.assertEqual(request('/health/ready')[0], 503)
            self.assertTrue(all(not key.startswith('__Host-') for key in jar))
        finally:
            server.shutdown()
            thread.join(5)
            server.server_close()


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'sessions.db')
        self.box = MeteringOutbox(self.path, SELLER, PRODUCT)
        self.addCleanup(self.box.close)
        self.sessions = BrowserSessions(self.box, ISSUER, ORIGIN)
        self.principal = Principal(ISSUER, 'session-user', NOW + timedelta(minutes=10))

    def test_random_tokens_digests_caps_and_reopen(self):
        issued = self.sessions.issue(self.principal, NOW, pending=digest('synthetic-claim'))
        self.assertEqual(issued.expires, int(NOW.timestamp()) + 600)
        self.assertNotIn(issued.token, repr(issued))
        self.assertNotIn(issued.csrf, repr(issued))
        dump = '\n'.join(self.box.db.iterdump())
        self.assertNotIn(issued.token, dump)
        self.assertNotIn(issued.csrf, dump)
        other = MeteringOutbox(self.path, SELLER, PRODUCT)
        try:
            session = BrowserSessions(other, ISSUER, ORIGIN).authenticate(issued.token, NOW)
            self.assertEqual(session.principal, self.principal)
            self.assertEqual(session.pending, digest('synthetic-claim'))
        finally:
            other.close()

    def test_forged_unknown_and_malformed_cookie_denied(self):
        for token in (None, '', 'bad', secrets.token_urlsafe(32), ['bad']):
            with self.assertRaises(MarketplaceDenied):
                self.sessions.authenticate(token, NOW)

    def test_cross_session_csrf_swap_denied(self):
        first = self.sessions.issue(self.principal, NOW)
        second = self.sessions.issue(self.principal, NOW)
        for cookie, form in ((first.csrf, second.csrf), (second.csrf, second.csrf), (None, first.csrf)):
            with self.assertRaises(MarketplaceDenied):
                self.sessions.authorize_post(first.token, cookie, form, NOW)
        self.sessions.authorize_post(first.token, first.csrf, first.csrf, NOW)

    def test_invalid_principal_context_and_lifetime_denied(self):
        for principal in (None, dataclasses.replace(self.principal, issuer='https://evil.test'),
                          dataclasses.replace(self.principal, expires_at=NOW),
                          dataclasses.replace(self.principal, expires_at=NOW + timedelta(seconds=901)),
                          dataclasses.replace(self.principal, subject='')):
            with self.assertRaises(MarketplaceDenied):
                self.sessions.issue(principal, NOW)
        with self.assertRaises(MarketplaceDenied):
            self.sessions.issue(self.principal, NOW, pending='raw-claim')

    def test_revoke_and_pending_context_rechecked_inside_transaction(self):
        credentials = self.sessions.issue(self.principal, NOW, pending=digest('claim-one'))
        with self.assertRaises(MarketplaceDenied):
            self.sessions.clear_pending(credentials.token, digest('claim-two'), NOW)
        self.sessions.clear_pending(credentials.token, digest('claim-one'), NOW)
        self.assertIsNone(self.sessions.authenticate(credentials.token, NOW).pending)
        self.sessions.revoke(credentials.token, NOW)
        self.sessions.revoke(credentials.token, NOW)
        with self.assertRaises(MarketplaceDenied):
            self.sessions.authenticate(credentials.token, NOW)

    def test_partial_rotation_failure_preserves_previous_session(self):
        first = self.sessions.issue(self.principal, NOW)
        self.box.db.execute("CREATE TRIGGER fail_session BEFORE INSERT ON browser_sessions BEGIN SELECT RAISE(ABORT,'synthetic abort'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.sessions.issue(self.principal, NOW, previous=first.token)
        self.sessions.authenticate(first.token, NOW)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM browser_sessions').fetchone()[0], 1)

    def test_expiry_regression_and_abandoned_session_cleanup(self):
        issued = self.sessions.issue(self.principal, NOW)
        for stamp in (NOW - timedelta(seconds=1), NOW + timedelta(seconds=600)):
            with self.assertRaises(MarketplaceDenied):
                self.sessions.authenticate(issued.token, stamp)
        future = NOW + timedelta(seconds=601)
        self.sessions.issue(dataclasses.replace(self.principal, expires_at=future + timedelta(seconds=60)), future)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM browser_sessions').fetchone()[0], 1)

    def test_configuration_cannot_switch_origin_or_issuer(self):
        for issuer, origin in ((ISSUER + '/other', ORIGIN), (ISSUER, ORIGIN + ':444')):
            with self.assertRaises(MeteringConflict):
                BrowserSessions(self.box, issuer, origin)
        with self.assertRaises(ValueError):
            BrowserSessions(self.box, ISSUER, 'https://account.example.test/path')


class PersonalOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = str(Path(self.directory.name) / 'org.db')
        self.box = MeteringOutbox(self.path, SELLER, PRODUCT)
        self.addCleanup(self.box.close)
        self.registry = RegistrationRegistry(self.box, None, ISSUER)
        self.principal = Principal(ISSUER, 'personal-user', NOW + timedelta(minutes=10))

    def test_only_own_workspace_no_caller_role_or_resource_and_repeat_idempotent(self):
        org = self.registry.create_personal_organization(self.principal, NOW)
        self.assertEqual(self.registry.create_personal_organization(self.principal, NOW), org)
        self.assertEqual(self.registry.list_organizations(self.principal, NOW), [{'org': org, 'role': 'owner'}])
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM provisioning_intents').fetchone()[0], 0)
        other = dataclasses.replace(self.principal, subject='other-subject')
        self.assertNotEqual(self.registry.create_personal_organization(other, NOW), org)

    def test_anonymous_expired_foreign_identity_denied(self):
        for principal in (None, dataclasses.replace(self.principal, issuer='https://evil.test'),
                          dataclasses.replace(self.principal, expires_at=NOW)):
            with self.assertRaises(MarketplaceDenied):
                self.registry.create_personal_organization(principal, NOW)

    def test_revoked_or_downgraded_owner_is_never_restored(self):
        org = self.registry.create_personal_organization(self.principal, NOW)
        for role in ('member', None):
            self.registry.set_membership(org, self.principal.subject, role)
            with self.assertRaises(MarketplaceDenied):
                self.registry.create_personal_organization(self.principal, NOW)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM personal_organizations').fetchone()[0], 1)

    def test_partial_membership_insert_rolls_back_personal_record(self):
        self.box.db.execute("CREATE TRIGGER fail_owner BEFORE INSERT ON org_memberships BEGIN SELECT RAISE(ABORT,'synthetic abort'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.create_personal_organization(self.principal, NOW)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM personal_organizations').fetchone()[0], 0)
        self.box.db.execute('DROP TRIGGER fail_owner')
        self.registry.create_personal_organization(self.principal, NOW)

    def test_concurrent_creation_one_workspace_and_membership(self):
        barrier = threading.Barrier(2)
        results, errors = [], []
        def create():
            box = MeteringOutbox(self.path, SELLER, PRODUCT)
            try:
                registry = RegistrationRegistry(box, None, ISSUER)
                barrier.wait(timeout=5)
                results.append(registry.create_personal_organization(self.principal, NOW))
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                box.close()
        threads = [threading.Thread(target=create) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(self.box.db.execute('SELECT count(*) FROM org_memberships').fetchone()[0], 1)

    def test_real_process_exit_after_commit_and_before_outer_commit(self):
        script = '''import os,sys
from datetime import datetime,timedelta,timezone
from marketplace_metering import MeteringOutbox
from marketplace_registration import Principal,RegistrationRegistry
now=datetime(2026,10,29,10,tzinfo=timezone.utc)
box=MeteringOutbox(sys.argv[1],'999999999999','synthetic-product')
r=RegistrationRegistry(box,None,'https://identity.example.test')
p=Principal('https://identity.example.test','personal-user',now+timedelta(minutes=10))
if sys.argv[2]=='rollback':
 with box.transaction():
  r.create_personal_organization(p,now)
  os._exit(74)
r.create_personal_organization(p,now)
os._exit(73)
'''
        for mode, count, code in (('rollback', 0, 74), ('commit', 1, 73)):
            result = subprocess.run([sys.executable, '-c', script, self.path, mode], cwd=Path(__file__).parent,
                capture_output=True, timeout=15)
            self.assertEqual(result.returncode, code)
            self.assertEqual(self.box.db.execute('SELECT count(*) FROM personal_organizations').fetchone()[0], count)
        org = self.registry.create_personal_organization(self.principal, NOW)
        self.assertEqual(self.box.db.execute('SELECT org FROM personal_organizations').fetchone()[0], org)


if __name__ == '__main__':
    unittest.main()
