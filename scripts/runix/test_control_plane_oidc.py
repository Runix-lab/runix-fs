"""OIDC foundation: real signatures, durable one-use correlation and failures."""
import base64
import dataclasses
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes
from jwt.algorithms import RSAAlgorithm

from control_plane_auth import AccessTokenVerifier
from control_plane_oidc import (CodeTokenClient, DENIED, IdTokenVerifier, OidcFlow,
    OidcProvider, UNAVAILABLE, digest, endpoint_request, s256, strict_json)
from local_oidc_provider import cleanup_owned
from marketplace_adapter import MarketplaceDenied
from marketplace_metering import MeteringConflict, MeteringOutbox

NOW = datetime(2026, 10, 29, 6, tzinfo=timezone.utc)
CONFIG = OidcProvider('https://identity.example.test', 'runix-fs-test',
    'https://identity.example.test/authorize', 'https://identity.example.test/token',
    'https://fs.example.test/callback')


class OidcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = json.loads(RSAAlgorithm.to_jwk(cls.private.public_key()))
        cls.public.update(kid='test-key', alg='RS256', use='sig')
        cls.jwks = {'keys': [cls.public]}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'login.db'
        self.store = self.open_store()
        self.addCleanup(self.store.db.close)
        self.verifier = IdTokenVerifier(CONFIG, self.jwks)
        self.client = Mock(provider=CONFIG)
        self.flow = OidcFlow(self.store, CONFIG, self.verifier, self.client)
        self.browser = secrets.token_urlsafe(32)
        self.start = self.flow.begin(self.browser, NOW)
        self.query = parse_qs(urlsplit(self.start.authorization_url).query)
        self.nonce = self.query['nonce'][0]
        self.payload = dict(iss=CONFIG.issuer, aud=CONFIG.client_id, sub='test-subject', nonce=self.nonce,
            iat=int(NOW.timestamp()), exp=int(NOW.timestamp()) + 1800)
        self.client.exchange.side_effect = lambda *_: (self.token(), 'synthetic-access')

    def open_store(self):
        return MeteringOutbox(self.path, '123456789012', 'synthetic-product')

    def token(self, payload=None, private=None, headers=None):
        return jwt.encode(self.payload if payload is None else payload, private or self.private,
                          algorithm='RS256', headers=headers or {'kid': 'test-key', 'typ': 'JWT'})

    def verify(self, token):
        return self.verifier.verify(token, NOW, digest(self.nonce), code='test-code', access_token='synthetic-access')

    def complete(self, **kwargs):
        args = dict(state=self.start.state, browser_secret=self.browser, now=NOW,
                    code='test-code', clock=lambda: NOW)
        args.update(kwargs)
        return self.flow.complete(**args)

    def test_real_id_signature_returns_capped_identity_not_org_role(self):
        result = self.verify(self.token(dict(self.payload, isAdmin=True, organization='attacker')))
        self.assertEqual(result.subject, 'test-subject')
        self.assertEqual(result.expires_at, NOW + timedelta(minutes=15))
        self.assertFalse(hasattr(result, 'organization'))
        access = AccessTokenVerifier(CONFIG.issuer, CONFIG.client_id, [CONFIG.client_id], self.jwks)
        with self.assertRaises(MarketplaceDenied):
            access.verify(self.token(), NOW)

    def test_foreign_key_tampering_unsigned_and_hmac_denied(self):
        parts = self.token().split('.')
        parts[1] = base64.urlsafe_b64encode(json.dumps(dict(self.payload, sub='attacker')).encode()).rstrip(b'=').decode()
        tokens = [self.token(private=self.other), '.'.join(parts),
                  jwt.encode(self.payload, None, algorithm='none'),
                  jwt.encode(self.payload, 'synthetic-hmac-key-with-at-least-32-bytes', algorithm='HS256')]
        for token in tokens:
            with self.subTest(kind=token.split('.')[0]):
                with self.assertRaisesRegex(MarketplaceDenied, '^' + DENIED + '$'):
                    self.verify(token)

    def test_missing_claims_denied(self):
        for key in self.payload:
            payload = dict(self.payload)
            del payload[key]
            with self.subTest(key=key), self.assertRaises(MarketplaceDenied):
                self.verify(self.token(payload))

    def test_wrong_claims_and_time_types_denied(self):
        stamp = int(NOW.timestamp())
        values = [('iss', CONFIG.issuer + '/other'), ('sub', ''), ('sub', 1), ('aud', 'foreign'),
            ('aud', [CONFIG.client_id, CONFIG.client_id]), ('aud', [CONFIG.client_id, 'other']),
            ('azp', 'other'), ('nonce', 'wrong'), ('nonce', ['bad']),
            ('iat', stamp + 1), ('iat', True), ('exp', stamp), ('exp', stamp + 3601),
            ('exp', float(stamp + 30)), ('nbf', stamp + 1), ('nbf', True), ('auth_time', stamp + 1)]
        for key, value in values:
            with self.subTest(key=key, value=value), self.assertRaises(MarketplaceDenied):
                self.verify(self.token(dict(self.payload, **{key: value})))

    def test_multi_audience_requires_correct_authorized_party(self):
        self.verify(self.token(dict(self.payload, aud=[CONFIG.client_id, 'other'], azp=CONFIG.client_id)))

    def test_protected_header_restrictions(self):
        for change in ({'typ': 'at+jwt'}, {'kid': 'unknown'}, {'jku': 'https://evil.test/key'},
                       {'x5u': 'file:///keys'}, {'jwk': self.public}, {'crit': []}, {'b64': True}):
            header = dict(kid='test-key', typ='JWT', **{})
            header.update(change)
            # Sign exact wire headers: the encoder strips b64=True itself.
            header['alg'] = 'RS256'
            def segment(value):
                return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=')
            wire = segment(header) + b'.' + segment(self.payload)
            signed = wire + b'.' + base64.urlsafe_b64encode(self.private.sign(
                wire, padding.PKCS1v15(), hashes.SHA256())).rstrip(b'=')
            with self.subTest(change=change), self.assertRaises(MarketplaceDenied):
                self.verify(signed.decode())

    def test_optional_hashes_verified(self):
        def half(value):
            return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:16]).rstrip(b'=').decode()
        self.verify(self.token(dict(self.payload, c_hash=half('test-code'), at_hash=half('synthetic-access'))))
        for key in ('c_hash', 'at_hash'):
            with self.subTest(key=key), self.assertRaises(MarketplaceDenied):
                self.verify(self.token(dict(self.payload, **{key: 'wrong'})))

    def test_login_start_has_s256_and_no_plain_verifier_or_secret_state(self):
        row = self.store.db.execute('SELECT * FROM oidc_states').fetchone()
        self.assertEqual(self.query['code_challenge_method'], ['S256'])
        self.assertEqual(self.query['code_challenge'], [s256(row['verifier'])])
        self.assertEqual(row['state'], digest(self.start.state))
        self.assertEqual(row['browser'], digest(self.browser))
        self.assertEqual(row['nonce'], digest(self.nonce))
        self.assertNotIn(row['verifier'], self.start.authorization_url)
        self.assertNotIn(self.start.state, repr(self.start))
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_valid_completion_consumes_before_network_and_clears_verifier(self):
        def exchange(code, verifier):
            row = self.store.db.execute('SELECT * FROM oidc_states').fetchone()
            self.assertIsNotNone(row['consumed'])
            self.assertIsNone(row['verifier'])
            self.assertFalse(self.store.db.in_transaction)
            self.assertEqual(self.query['code_challenge'][0], s256(verifier))
            return self.token(), 'synthetic-access'
        self.client.exchange.side_effect = exchange
        self.assertEqual(self.complete().subject, 'test-subject')
        with self.assertRaises(MarketplaceDenied):
            self.complete()
        self.assertEqual(self.client.exchange.call_count, 1)

    def test_wrong_browser_does_not_burn_legitimate_login(self):
        with self.assertRaises(MarketplaceDenied):
            self.complete(browser_secret=secrets.token_urlsafe(32))
        self.client.exchange.assert_not_called()
        self.complete()

    def test_expiry_clock_regression_and_malformed_state(self):
        for changes in ({'now': NOW - timedelta(seconds=1)}, {'now': NOW + timedelta(seconds=600)},
                        {'state': 'wrong'}, {'browser_secret': None}, {'state': None}):
            with self.subTest(changes=changes), self.assertRaises(MarketplaceDenied):
                self.complete(**changes)
        self.client.exchange.assert_not_called()

    def test_provider_error_ambiguous_or_missing_code_consumes(self):
        for kwargs in ({'error': 'denied'}, {'code': None}, {'code': 'x\nsecret'},
                       {'error': 'error', 'code': 'both'}):
            start = self.flow.begin(self.browser, NOW)
            with self.subTest(kwargs=kwargs), self.assertRaises(MarketplaceDenied):
                self.complete(state=start.state, **kwargs)
            row = self.store.db.execute('SELECT consumed,verifier FROM oidc_states WHERE state=?', (digest(start.state),)).fetchone()
            self.assertEqual(tuple(row), (int(NOW.timestamp()), None))
        self.client.exchange.assert_not_called()

    def test_lost_token_response_does_not_reuse_consumed_state_after_restart(self):
        self.client.exchange.side_effect = MarketplaceDenied(UNAVAILABLE)
        with self.assertRaisesRegex(MarketplaceDenied, UNAVAILABLE):
            self.complete()
        second = self.open_store()
        try:
            flow = OidcFlow(second, CONFIG, self.verifier, self.client)
            with self.assertRaises(MarketplaceDenied):
                flow.complete(self.start.state, self.browser, NOW, code='test-code', clock=lambda: NOW)
        finally:
            second.db.close()
        self.assertEqual(self.client.exchange.call_count, 1)

    def test_process_crash_after_consumption_is_durable(self):
        code = '''import sys,os
from datetime import datetime,timezone
from unittest.mock import Mock
from control_plane_oidc import OidcFlow,OidcProvider
from marketplace_metering import MeteringOutbox
config=OidcProvider(*sys.argv[4:9])
store=MeteringOutbox(sys.argv[1],'123456789012','synthetic-product')
client=Mock(provider=config)
client.exchange.side_effect=lambda *_: os._exit(73)
flow=OidcFlow(store,config,Mock(provider=config),client)
flow.complete(sys.argv[2],sys.argv[3],datetime(2026,10,29,6,tzinfo=timezone.utc),code='test-code')
'''
        args = [CONFIG.issuer, CONFIG.client_id, CONFIG.authorization_endpoint, CONFIG.token_endpoint, CONFIG.redirect_uri]
        result = subprocess.run([sys.executable, '-c', code, str(self.path), self.start.state, self.browser, *args],
            cwd=Path(__file__).parent, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 73)
        with self.assertRaises(MarketplaceDenied):
            self.complete()
        self.client.exchange.assert_not_called()

    def test_parallel_callbacks_exchange_exactly_once(self):
        barrier = threading.Barrier(2)
        outcomes, calls, errors = [], [], []
        def work():
            store = self.open_store()
            client = Mock(provider=CONFIG)
            client.exchange.side_effect = lambda *_: (calls.append(1) or self.token(), 'synthetic-access')
            try:
                flow = OidcFlow(store, CONFIG, self.verifier, client)
                barrier.wait(timeout=5)
                flow.complete(self.start.state, self.browser, NOW, code='test-code', clock=lambda: NOW)
                outcomes.append('ok')
            except MarketplaceDenied:
                outcomes.append('denied')
            except Exception as error:
                errors.append(type(error).__name__)
            finally:
                store.db.close()
        threads = [threading.Thread(target=work) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(outcomes), ['denied', 'ok'])
        self.assertEqual(len(calls), 1)

    def test_rollback_never_sends_code(self):
        self.store.db.execute("CREATE TRIGGER fail_consume BEFORE UPDATE ON oidc_states BEGIN SELECT RAISE(ABORT,'synthetic abort'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.complete()
        self.client.exchange.assert_not_called()
        self.assertIsNone(self.store.db.execute('SELECT consumed FROM oidc_states').fetchone()[0])
        self.store.db.execute('DROP TRIGGER fail_consume')
        self.complete()

    def test_nested_transaction_refused_before_network(self):
        with self.store.transaction(), self.assertRaises(RuntimeError):
            self.complete()
        self.client.exchange.assert_not_called()

    def test_network_delay_and_clock_regression_deny_identity(self):
        for delta in (-1, 30):
            start = self.flow.begin(self.browser, NOW)
            with self.subTest(delta=delta), self.assertRaises(MarketplaceDenied):
                self.complete(state=start.state, clock=lambda: NOW + timedelta(seconds=delta))

    def test_immutable_database_config_and_component_match(self):
        changed = dataclasses.replace(CONFIG, client_id='other')
        with self.assertRaises(MeteringConflict):
            OidcFlow(self.store, changed, Mock(provider=changed), Mock(provider=changed))
        with self.assertRaises(ValueError):
            OidcFlow(self.store, CONFIG, Mock(provider=changed), self.client)

    def test_expired_state_pruned_on_new_login(self):
        self.flow.begin(self.browser, NOW + timedelta(seconds=600))
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM oidc_states').fetchone()[0], 1)

    def test_config_rejects_untrusted_endpoints(self):
        for changes in ({'issuer': 'http://identity.example.test'}, {'token_endpoint': 'https://evil.test/token'},
                        {'authorization_endpoint': CONFIG.authorization_endpoint + '?next=evil'},
                        {'redirect_uri': 'https://user:password@fs.example.test/callback'},
                        {'issuer': CONFIG.issuer + '#fragment'}, {'client_id': ''},
                        {'allow_loopback_testing': 1}, {'redirect_uri': 'http://10.0.0.1/callback', 'allow_loopback_testing': True}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                dataclasses.replace(CONFIG, **changes)
        OidcProvider('http://127.0.0.1:8000', 'test', 'http://127.0.0.1:8000/auth',
                     'http://127.0.0.1:8000/token', 'http://127.0.0.1:8000/callback', True)

    def test_exchange_fixed_post_basic_pkce_and_no_secret_in_uri(self):
        request = Mock(return_value=(200, {}, json.dumps(dict(id_token='id-token', access_token='access-token', token_type='Bearer')).encode()))
        client = CodeTokenClient(CONFIG, 'synthetic-client-secret', request)
        self.assertEqual(client.exchange('test-code', self.browser), ('id-token', 'access-token'))
        args, kwargs = request.call_args
        self.assertEqual(args, (CONFIG.token_endpoint,))
        self.assertEqual(kwargs['method'], 'POST')
        self.assertTrue(kwargs['headers']['Authorization'].startswith('Basic '))
        params = parse_qs(kwargs['data'].decode())
        self.assertEqual(params['code_verifier'], [self.browser])
        self.assertEqual(params['redirect_uri'], [CONFIG.redirect_uri])
        self.assertNotIn('client_secret', params)

    def test_exchange_failures_redact_credentials_and_never_follow_redirect(self):
        values = [(302, {'Location': 'https://evil.test/'}, b''), (500, {}, b'test-code'),
                  (200, {}, b'{"id_token":"one","id_token":"two","access_token":"valid","token_type":"Bearer"}'), (200, {}, b'{}'),
                  (200, {}, b'null'), (200, {}, b'x' * 65537), (200, {}, b'not-json')]
        for response in values:
            request = Mock(return_value=response)
            with self.subTest(status=response[0]), self.assertRaisesRegex(MarketplaceDenied, '^' + UNAVAILABLE + '$'):
                CodeTokenClient(CONFIG, 'secret', request).exchange('test-code', self.browser)
            self.assertEqual(request.call_count, 1)
        request = Mock(side_effect=OSError('test-code and secret'))
        with self.assertRaisesRegex(MarketplaceDenied, '^' + UNAVAILABLE + '$'):
            CodeTokenClient(CONFIG, 'secret', request).exchange('test-code', self.browser)

    def test_direct_tls_transport_closes_and_does_not_retry(self):
        connection = Mock()
        connection.getresponse.return_value.status = 302
        connection.getresponse.return_value.getheaders.return_value = [('Location', 'https://evil.test')]
        connection.getresponse.return_value.read.return_value = b''
        with patch('control_plane_oidc.http.client.HTTPSConnection', return_value=connection):
            result = endpoint_request(CONFIG.token_endpoint, data=b'body', headers={}, method='POST')
        self.assertEqual(result[0], 302)
        connection.request.assert_called_once()
        connection.close.assert_called_once()
        connection.getresponse.return_value.read.return_value = b'x' * 65537
        with patch('control_plane_oidc.http.client.HTTPSConnection', return_value=connection), self.assertRaises(ValueError):
            endpoint_request(CONFIG.token_endpoint, data=b'body', headers={}, method='POST')
        self.assertEqual(connection.close.call_count, 2)


class FixtureCleanupTests(unittest.TestCase):
    def run_cleanup(self, failing=None, leftovers=False):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory)
            envfile = runtime / 'fixture.env'
            envfile.write_text('synthetic-secret')
            calls = []
            def docker(*args, **kwargs):
                calls.append(args)
                if args[0] == failing:
                    raise subprocess.TimeoutExpired('docker', 1)
                return Mock(stdout=('owned\n' if leftovers else 'unrelated-existing\n'))
            if failing in {'rm', 'network', 'ps'} or leftovers:
                with self.assertRaisesRegex(RuntimeError, 'cleanup could not be confirmed'):
                    cleanup_owned(docker, runtime, envfile, 'owned', 'owned-client', 'owned-network')
            else:
                cleanup_owned(docker, runtime, envfile, 'owned', 'owned-client', 'owned-network')
            self.assertFalse(envfile.exists())
            self.assertIn(('rm', '-fv', 'owned-client', 'owned'), calls)
            self.assertIn(('network', 'rm', 'owned-network'), calls)
            self.assertFalse(any('unrelated-existing' in arg for call in calls for arg in call))

    def test_cleanup_success(self):
        self.run_cleanup()

    def test_log_failure_does_not_skip_removal(self):
        self.run_cleanup('logs')

    def test_removal_failure_still_removes_network_and_secret(self):
        self.run_cleanup('rm')

    def test_network_failure_still_checks_inventory(self):
        self.run_cleanup('network')

    def test_unavailable_inventory_never_claims_clean(self):
        self.run_cleanup('ps')

    def test_leftovers_never_claim_clean(self):
        self.run_cleanup(leftovers=True)


if __name__ == '__main__':
    unittest.main()
