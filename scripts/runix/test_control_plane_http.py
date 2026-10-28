"""Actual signed-token HTTP boundary; SDK Stubber is not a real buyer purchase."""
import copy
import http.client
import io
import json
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock
from wsgiref.simple_server import WSGIServer
from wsgiref.util import setup_testing_defaults

import boto3
import jwt
from botocore.stub import Stubber
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from control_plane_auth import AccessTokenVerifier
from control_plane_http import ControlPlaneApp, QuietRequestHandler
from marketplace_adapter import RegistrationGateway
from marketplace_lifecycle import NegativeLifecycle
from marketplace_metering import MeteringOutbox
from marketplace_registration import RegistrationRegistry

ISSUER = 'https://identity.example.test'
ORIGIN = 'https://control.example.test'
SELLER = '999999999999'
PRODUCT = 'synthetic-product'
PURCHASE = dict(CustomerAWSAccountId='123456789012',
    LicenseArn='arn:aws:license-manager:us-east-1:999999999999:license:http-test',
    ProductCode=PRODUCT, Metadata={'AgreementId': 'agmt-http'})


class ControlPlaneHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = json.loads(RSAAlgorithm.to_jwk(cls.private.public_key()))
        public.update(kid='http-test-key', use='sig', alg='RS256')
        cls.verifier = AccessTokenVerifier(ISSUER, 'runix-fs-api', ['console-test'], {'keys': [public]})

    def setUp(self):
        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.temp = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp.name) / 'control.sqlite')
        self.client = boto3.client('meteringmarketplace', region_name='us-east-1', aws_access_key_id='test-only', aws_secret_access_key='test-only')
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        self.gateway = RegistrationGateway(sts, self.client, SELLER, PRODUCT)
        self.app = ControlPlaneApp(self.database, SELLER, PRODUCT, self.verifier, ORIGIN, self.gateway)
        self.box = MeteringOutbox(self.database, SELLER, PRODUCT)
        self.registry = RegistrationRegistry(self.box, self.gateway, ISSUER)
        self.registry.set_membership('org-one', 'owner-test', 'owner')
        self.registry.set_membership('org-one', 'member-test', 'member')

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def token(self, subject='owner-test', **changes):
        payload = dict(iss=ISSUER, aud='runix-fs-api', sub=subject, client_id='console-test',
            jti='http-' + uuid.uuid4().hex, iat=int(self.now.timestamp()),
            exp=int((self.now + timedelta(minutes=5)).timestamp()), scope='runix:fs')
        payload.update(changes)
        return jwt.encode(payload, self.private, algorithm='RS256', headers={'typ': 'at+jwt', 'kid': 'http-test-key'})

    def request(self, path, method='GET', body=b'', content_type='application/json', token=None, **overrides):
        environ = {}
        setup_testing_defaults(environ)
        route, separator, query = path.partition('?')
        environ.update(PATH_INFO=route, QUERY_STRING=query, REQUEST_METHOD=method,
                       HTTP_HOST='control.example.test', REMOTE_ADDR='127.0.0.1', CONTENT_TYPE=content_type,
                       CONTENT_LENGTH=str(len(body)), **{'wsgi.url_scheme': 'https', 'wsgi.input': io.BytesIO(body)})
        if token is not None:
            environ['HTTP_AUTHORIZATION'] = 'Bearer ' + token
        environ.update(overrides)
        response = {}
        def start(status, headers):
            response['status'] = int(status.split(' ')[0])
            response['headers'] = dict(headers)
        output = b''.join(self.app(environ, start))
        response['body'] = json.loads(output)
        return response

    def callback(self):
        with Stubber(self.client) as stub:
            stub.add_response('resolve_customer', PURCHASE, {'RegistrationToken': 'synthetic-aws-token'})
            result = self.request('/marketplace/register', 'POST', urlencode({'x-amzn-marketplace-token': 'synthetic-aws-token'}).encode(), 'application/x-www-form-urlencoded')
            stub.assert_no_pending_responses()
        self.assertEqual(result['status'], 202)
        self.assertEqual(result['body']['status'], 'pending_account_binding')
        return result['body']['claim']

    def bind(self, claim, subject='owner-test', org='org-one'):
        return self.request('/api/marketplace/bind', 'POST', json.dumps({'organization_id': org, 'claim': claim}).encode(), token=self.token(subject))

    def test_callback_bind_and_purchase_read_are_real_pending_workflow(self):
        claim = self.callback()
        result = self.bind(claim)
        self.assertEqual(result['status'], 200)
        self.assertEqual(result['body']['status'], 'pending_license_verification')
        self.assertNotIn('endpoint', result['body'])
        self.assertNotIn('credentials', result['body'])
        listing = self.request('/api/fs/purchases?organization_id=org-one', token=self.token())
        self.assertEqual(listing['status'], 200)
        self.assertEqual(len(listing['body']['purchases']), 1)
        self.assertEqual(self.bind(claim)['body'], result['body'])
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 1)

    def test_callback_malformed_or_repeated_token_never_redeems(self):
        for body in (b'', b'wrong=token', b'x-amzn-marketplace-token=',
                     b'x-amzn-marketplace-token=a&x-amzn-marketplace-token=b',
                     b'x-amzn-marketplace-token=a&CustomerAWSAccountId=123456789012',
                     b'x-amzn-marketplace-token=%FF'):
            result = self.request('/marketplace/register', 'POST', body, 'application/x-www-form-urlencoded')
            self.assertEqual(result['status'], 400)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 0)

    def test_bad_registration_and_sdk_error_are_sanitized(self):
        form = urlencode({'x-amzn-marketplace-token': 'sensitive-fixture'}).encode()
        with Stubber(self.client) as stub:
            stub.add_client_error('resolve_customer', service_error_code='InvalidTokenException', service_message='sensitive-fixture must never leak')
            result = self.request('/marketplace/register', 'POST', form, 'application/x-www-form-urlencoded')
        self.assertEqual(result['status'], 403)
        self.assertNotIn('sensitive-fixture', json.dumps(result))
        with Stubber(self.client) as stub:
            stub.add_client_error('resolve_customer', service_error_code='ThrottlingException', service_message='private backend detail')
            result = self.request('/marketplace/register', 'POST', form, 'application/x-www-form-urlencoded')
        self.assertEqual(result['status'], 503)
        self.assertNotIn('private backend', json.dumps(result))

    def test_anonymous_cookie_query_and_forged_context_are_denied(self):
        for path, headers in (
            ('/api/fs/organizations', {}),
            ('/api/fs/organizations', {'HTTP_COOKIE': 'session=fake'}),
            ('/api/fs/organizations?access_token=' + self.token(), {}),
            ('/api/fs/organizations', {'HTTP_AUTHORIZATION': 'Bearer not-a-jwt'}),
            ('/api/fs/organizations', {'HTTP_X_USER': 'owner-test', 'HTTP_X_ROLE': 'admin'}),
        ):
            self.assertEqual(self.request(path, **headers)['status'], 401)

    def test_signed_tokens_with_wrong_audience_scope_or_expiry_deny(self):
        for changes in ({'aud': 'another-service'}, {'scope': 'unrelated'},
                        {'exp': int(self.now.timestamp())}, {'iss': ISSUER + '/other'}):
            self.assertEqual(self.request('/api/fs/organizations', token=self.token(**changes))['status'], 401)

    def test_organizations_are_server_derived_and_revocation_is_immediate(self):
        self.registry.set_membership('org-other', 'other-subject', 'owner')
        result = self.request('/api/fs/organizations', token=self.token())
        self.assertEqual(result['body']['organizations'], [{'org': 'org-one', 'role': 'owner'}])
        self.registry.set_membership('org-one', 'owner-test', None)
        result = self.request('/api/fs/organizations', token=self.token())
        self.assertEqual(result['body']['organizations'], [])
        self.assertEqual(self.request('/api/fs/purchases?organization_id=org-one', token=self.token())['status'], 403)

    def test_cross_org_and_member_bind_denied_but_member_can_read(self):
        claim = self.callback()
        self.assertEqual(self.bind(claim, org='org-other')['status'], 403)
        self.assertEqual(self.bind(claim, subject='member-test')['status'], 403)
        self.assertEqual(self.bind(claim)['status'], 200)
        self.assertEqual(self.request('/api/fs/purchases?organization_id=org-one', token=self.token('member-test'))['status'], 200)
        self.assertEqual(self.request('/api/fs/purchases?organization_id=org-other', token=self.token())['status'], 403)

    def test_binding_body_schema_and_duplicate_keys_are_rejected(self):
        claim = self.callback()
        for value in (
            b'{"organization_id":"org-one","organization_id":"org-other","claim":"x"}',
            b'[]', b'{"organization_id":NaN,"claim":"x"}', b'not-json', b'\xff',
            json.dumps({'organization_id': 'org-one', 'claim': claim, 'role': 'owner'}).encode(),
            json.dumps({'organization_id': '../other', 'claim': claim}).encode(),
        ):
            self.assertEqual(self.request('/api/marketplace/bind', 'POST', value, token=self.token())['status'], 400)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)

    def test_stopped_purchase_cannot_be_bound_through_http(self):
        claim = self.callback()
        item = {'version': '0', 'id': str(uuid.uuid4()), 'detail-type': 'Purchase Agreement Ended - Proposer',
            'source': 'aws.agreement-marketplace', 'account': SELLER, 'region': 'us-east-1', 'time': self.now.isoformat(),
            'resources': ['arn:aws:aws-marketplace::aws:agreement:agmt-http'], 'detail': {'catalog': 'AWSMarketplace',
                'agreement': {'id': 'agmt-http', 'status': 'CANCELLED'},
                'acceptor': {'accountId': PURCHASE['CustomerAWSAccountId']}, 'proposer': {'accountId': SELLER}}}
        NegativeLifecycle(self.box, 'prod-http').apply(item, self.now)
        self.assertEqual(self.bind(claim)['status'], 403)

    def test_content_type_length_and_transfer_limits(self):
        form = b'x-amzn-marketplace-token=x'
        cases = [({'CONTENT_TYPE': 'text/plain'}, 415), ({'CONTENT_TYPE': 'application/x-www-form-urlencoded; charset=latin1'}, 415),
                 ({'CONTENT_LENGTH': ''}, 411), ({'CONTENT_LENGTH': '-1'}, 400), ({'CONTENT_LENGTH': '1,2'}, 400),
                 ({'CONTENT_LENGTH': '999999999999999999999999'}, 413),
                 ({'CONTENT_LENGTH': str(len(form) + 1)}, 400), ({'HTTP_TRANSFER_ENCODING': 'chunked'}, 400)]
        for changes, status in cases:
            self.assertEqual(self.request('/marketplace/register', 'POST', form, 'application/x-www-form-urlencoded', **changes)['status'], status)
        self.assertEqual(self.request('/api/marketplace/bind', 'POST', b'x' * 8193, token=self.token())['status'], 413)

    def test_foreign_host_origin_and_tls_spoofing_rejected(self):
        for change, status in (({'HTTP_HOST': 'attacker.example'}, 421),
                               ({'HTTP_ORIGIN': 'https://attacker.example'}, 403),
                               ({'wsgi.url_scheme': 'http', 'HTTP_X_FORWARDED_PROTO': 'https'}, 426)):
            self.assertEqual(self.request('/api/fs/organizations', token=self.token(), **change)['status'], status)
        self.assertNotIn('Access-Control-Allow-Origin', self.request('/api/fs/organizations', token=self.token())['headers'])

    def test_readiness_never_claims_unimplemented_delivery(self):
        self.assertEqual(self.request('/health/live')['body'], {'status': 'running'})
        ready = self.request('/health/ready')
        self.assertEqual(ready['status'], 503)
        self.assertEqual(ready['body']['reason'], 'delivery_not_configured')
        self.assertEqual(self.request('/api/fs/clusters', 'POST', token=self.token())['status'], 404)

    def test_methods_and_ambiguous_query_rejected(self):
        self.assertEqual(self.request('/marketplace/register')['status'], 405)
        self.assertEqual(self.request('/api/marketplace/bind', 'OPTIONS')['status'], 405)
        for path in ('/api/fs/purchases', '/api/fs/purchases?organization_id=org-one&organization_id=org-other',
                     '/api/fs/purchases?organization_id=org-one&LicenseArn=buyer-supplied', '/api/fs/organizations?role=admin'):
            self.assertEqual(self.request(path, token=self.token())['status'], 400)

    def test_all_responses_have_no_store_and_non_leaking_security_headers(self):
        for result in (self.request('/health/live'), self.request('/api/fs/organizations'), self.callback_response()):
            headers = result['headers']
            self.assertEqual(headers['Cache-Control'], 'no-store')
            self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            self.assertNotIn('Set-Cookie', headers)
        self.assertIn('WWW-Authenticate', self.request('/api/fs/organizations')['headers'])

    def callback_response(self):
        with Stubber(self.client) as stub:
            stub.add_response('resolve_customer', PURCHASE, {'RegistrationToken': 'x'})
            return self.request('/marketplace/register', 'POST', b'x-amzn-marketplace-token=x', 'application/x-www-form-urlencoded')

    def test_unavailable_aws_does_not_synthesize_purchase_and_existing_reads_work(self):
        self.app = ControlPlaneApp(self.database, SELLER, PRODUCT, self.verifier, ORIGIN, gateway=None)
        result = self.request('/marketplace/register', 'POST', b'x-amzn-marketplace-token=x', 'application/x-www-form-urlencoded')
        self.assertEqual(result['status'], 503)
        self.assertEqual(self.request('/api/fs/organizations', token=self.token())['status'], 200)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 0)

    def test_callback_sdk_identity_mismatch_creates_no_claim(self):
        with Stubber(self.client) as stub:
            stub.add_response('resolve_customer', dict(PURCHASE, ProductCode='another-product'), {'RegistrationToken': 'x'})
            result = self.request('/marketplace/register', 'POST', b'x-amzn-marketplace-token=x', 'application/x-www-form-urlencoded')
        self.assertEqual(result['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 0)

    def test_conflicting_resolved_buyer_is_409_and_original_claim_remains(self):
        original = self.callback()
        with Stubber(self.client) as stub:
            stub.add_response('resolve_customer', dict(PURCHASE, CustomerAWSAccountId='888888888888'), {'RegistrationToken': 'x'})
            result = self.request('/marketplace/register', 'POST', b'x-amzn-marketplace-token=x', 'application/x-www-form-urlencoded')
        self.assertEqual(result['status'], 409)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 1)
        self.assertEqual(self.bind(original)['status'], 200)

    def test_expired_claim_cannot_bind_over_http(self):
        claim = self.callback()
        self.box.db.execute('UPDATE registration_claims SET expires=?', (int(self.now.timestamp()),))
        self.assertEqual(self.bind(claim)['status'], 403)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)

    def test_concurrent_http_binding_uses_separate_connections_and_one_intent(self):
        claim = self.callback()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.bind(claim), range(2)))
        self.assertEqual([result['status'] for result in results], [200, 200])
        self.assertEqual(results[0]['body']['intent_id'], results[1]['body']['intent_id'])
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 1)

    def test_partial_binding_failure_is_sanitized_and_retry_is_atomic(self):
        claim = self.callback()
        self.box.db.execute("CREATE TRIGGER fail_http_intent BEFORE INSERT ON provisioning_intents BEGIN SELECT RAISE(ABORT, 'sensitive-db-message'); END")
        result = self.bind(claim)
        self.assertEqual(result['status'], 503)
        self.assertNotIn('sensitive-db-message', json.dumps(result))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)
        self.box.db.execute('DROP TRIGGER fail_http_intent')
        self.assertEqual(self.bind(claim)['status'], 200)

    def test_configuration_refuses_public_http_or_wrong_identity(self):
        for origin in ('http://public.example', 'https://user:pass@example.test', ORIGIN + '/redirect', ORIGIN + '?x=y'):
            with self.assertRaises(ValueError):
                ControlPlaneApp(self.database, SELLER, PRODUCT, self.verifier, origin)
        with self.assertRaises(ValueError):
            ControlPlaneApp('relative.sqlite', SELLER, PRODUCT, self.verifier, ORIGIN)
        with self.assertRaises(ValueError):
            ControlPlaneApp(self.database, SELLER, PRODUCT, None, ORIGIN)
        with self.assertRaises(ValueError):
            ControlPlaneApp(self.database, '111111111111', PRODUCT, self.verifier, ORIGIN, self.gateway)

    def test_real_loopback_http_round_trip_and_non_loopback_rejection(self):
        server = WSGIServer(('127.0.0.1', 0), QuietRequestHandler)
        origin = 'http://127.0.0.1:' + str(server.server_port)
        app = ControlPlaneApp(self.database, SELLER, PRODUCT, self.verifier, origin, self.gateway)
        server.set_app(app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            client.request('GET', '/api/fs/organizations', headers={'Authorization': 'Bearer ' + self.token()})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())['organizations'], [{'org': 'org-one', 'role': 'owner'}])
            client.request('GET', '/health/ready')
            response = client.getresponse()
            self.assertEqual(response.status, 503)
            response.read()
            client.close()
            with Stubber(self.client) as stub:
                stub.add_response('resolve_customer', PURCHASE, {'RegistrationToken': 'loopback-fixture'})
                client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
                body = urlencode({'x-amzn-marketplace-token': 'loopback-fixture'})
                client.request('POST', '/marketplace/register', body, {'Content-Type': 'application/x-www-form-urlencoded'})
                response = client.getresponse()
                self.assertEqual(response.status, 202)
                claim = json.loads(response.read())['claim']
                client.request('POST', '/api/marketplace/bind', json.dumps({'organization_id': 'org-one', 'claim': claim}),
                               {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.token()})
                response = client.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())['status'], 'pending_license_verification')
                client.close()
            # The cleartext exception is not valid for a non-loopback peer.
            env = dict(HTTP_HOST='127.0.0.1:' + str(server.server_port), REMOTE_ADDR='192.0.2.1',
                       PATH_INFO='/health/live', REQUEST_METHOD='GET', **{'wsgi.url_scheme': 'http'})
            status = []
            b''.join(app(env, lambda value, _headers: status.append(value)))
            self.assertTrue(status[0].startswith('426'))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
