"""Real ephemeral RSA signatures; no live IdP or committed private keys."""
import base64
import copy
import dataclasses
import hashlib
import hmac
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from control_plane_auth import AccessTokenVerifier, DENIED
from marketplace_adapter import MarketplaceDenied, RegistrationGateway
from marketplace_metering import MeteringOutbox
from marketplace_registration import RegistrationRegistry

NOW = datetime(2026, 10, 28, 4, tzinfo=timezone.utc)
ISSUER = 'https://identity.example.test'
AUDIENCE = 'runix-fs-api'
CLIENT = 'runix-console'


class AccessTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.public = json.loads(RSAAlgorithm.to_jwk(cls.private.public_key()))
        cls.public.update(kid='key-one', use='sig', alg='RS256')
        cls.other_public = json.loads(RSAAlgorithm.to_jwk(cls.other_private.public_key()))
        cls.other_public.update(kid='key-two', use='sig', alg='RS256')

    def setUp(self):
        self.verifier = AccessTokenVerifier(ISSUER, AUDIENCE, [CLIENT], {'keys': [self.public]})
        self.payload = dict(iss=ISSUER, aud=AUDIENCE, sub='subject-one', client_id=CLIENT,
                            jti='synthetic-jti', iat=int(NOW.timestamp()),
                            exp=int((NOW + timedelta(minutes=30)).timestamp()), scope='runix:fs')

    def token(self, payload=None, **headers):
        return jwt.encode(payload if payload is not None else self.payload, self.private,
                          algorithm='RS256', headers=dict(typ='at+jwt', kid='key-one', **headers))

    def denied(self, token, now=NOW):
        with self.assertRaises(MarketplaceDenied) as error:
            self.verifier.verify(token, now)
        self.assertEqual(str(error.exception), DENIED)

    def raw_token(self, header, hmac_key=None):
        # Create malicious wire fixtures without PyJWT's encoding sanitization.
        def segment(value):
            return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b'=')
        wire = segment(header) + b'.' + segment(self.payload)
        signature = (hmac.new(hmac_key, wire, hashlib.sha256).digest() if hmac_key else
                     self.private.sign(wire, padding.PKCS1v15(), hashes.SHA256()))
        return (wire + b'.' + base64.urlsafe_b64encode(signature).rstrip(b'=')).decode()

    def test_valid_signature_yields_capped_verified_context(self):
        principal = self.verifier.verify(self.token(), NOW)
        self.assertEqual(principal.issuer, ISSUER)
        self.assertEqual(principal.subject, 'subject-one')
        self.assertEqual(principal.expires_at, NOW + timedelta(minutes=15))
        payload = dict(self.payload, exp=int((NOW + timedelta(seconds=30)).timestamp()))
        self.assertEqual(self.verifier.verify(self.token(payload), NOW).expires_at, NOW + timedelta(seconds=30))

    def test_forged_and_modified_payloads_fail_real_signature_check(self):
        token = jwt.encode(self.payload, self.other_private, algorithm='RS256', headers={'typ': 'at+jwt', 'kid': 'key-one'})
        self.denied(token)
        parts = self.token().split('.')
        changed = dict(self.payload, sub='attacker')
        parts[1] = base64.urlsafe_b64encode(json.dumps(changed).encode()).decode().rstrip('=')
        self.denied('.'.join(parts))

    def test_algorithm_confusion_and_unsigned_tokens_denied(self):
        der = self.private.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.denied(self.raw_token({'alg': 'HS256', 'typ': 'at+jwt', 'kid': 'key-one'}, der))
        self.denied(jwt.encode(self.payload, None, algorithm='none', headers={'typ': 'at+jwt', 'kid': 'key-one'}))

    def test_id_tokens_and_key_urls_are_never_accepted(self):
        for headers in ({'typ': 'JWT'}, {'typ': 'id+jwt'}, {'kid': 'unknown'},
                        {'jku': 'https://attacker.example/keys'}, {'x5u': 'file:///etc/passwd'},
                        {'jwk': self.other_public}, {'crit': ['b64']}, {'b64': True}):
            merged = dict(typ='at+jwt', kid='key-one')
            merged.update(headers)
            merged['alg'] = 'RS256'
            with self.subTest(headers=list(headers)):
                self.denied(self.raw_token(merged))

    def test_wrong_claim_identity_scope_and_types_deny(self):
        for field, value in (('iss', ISSUER + '/other'), ('aud', 'other-api'), ('aud', [AUDIENCE]),
                             ('client_id', 'other-client'), ('client_id', ['bad']), ('sub', ''),
                             ('scope', 'runix:fs-other'), ('scope', ['runix:fs']),
                             ('scope', 'runix:fs\nadmin'), ('scope', 'runix:fs\tadmin'), ('jti', '')):
            with self.subTest(field=field, value=value):
                self.denied(self.token(dict(self.payload, **{field: value})))

    def test_required_claims_are_not_optional(self):
        for field in ('iss', 'aud', 'sub', 'client_id', 'jti', 'iat', 'exp', 'scope'):
            value = dict(self.payload)
            del value[field]
            with self.subTest(field=field):
                self.denied(self.token(value))

    def test_expired_future_and_non_integer_numeric_dates_deny(self):
        stamp = int(NOW.timestamp())
        for changes in ({'exp': stamp}, {'iat': stamp + 1}, {'nbf': stamp + 1},
                        {'nbf': True}, {'exp': stamp + 3601}, {'iat': -1},
                        {'iat': float(stamp)}, {'exp': str(stamp + 100)},
                        {'exp': True}, {'nbf': None}):
            with self.subTest(changes=changes):
                self.denied(self.token(dict(self.payload, **changes)))
        self.denied(self.token(), NOW.replace(tzinfo=None))

    def test_nbf_boundary_and_utc_offset(self):
        value = dict(self.payload, nbf=int(NOW.timestamp()))
        principal = self.verifier.verify(self.token(value), NOW.astimezone(timezone(timedelta(hours=8))))
        self.assertEqual(principal.expires_at, NOW + timedelta(minutes=15))

    def test_unknown_signer_requires_explicit_operator_key_rotation(self):
        token = jwt.encode(self.payload, self.other_private, algorithm='RS256', headers={'typ': 'at+jwt', 'kid': 'key-two'})
        self.denied(token)
        rotated = AccessTokenVerifier(ISSUER, AUDIENCE, [CLIENT], {'keys': [self.public, self.other_public]})
        self.assertEqual(rotated.verify(token, NOW).subject, 'subject-one')
        removed = AccessTokenVerifier(ISSUER, AUDIENCE, [CLIENT], {'keys': [self.other_public]})
        with self.assertRaises(MarketplaceDenied):
            removed.verify(self.token(), NOW)

    def test_malformed_and_oversized_bearer_values_deny(self):
        for value in (None, b'bytes', '', 'invalid', 'a.b.c', 'x' * 16385):
            self.denied(value)

    def test_invalid_pinned_key_material_is_rejected_at_configuration(self):
        weak = rsa.generate_private_key(public_exponent=65537, key_size=1024)
        weak_public = json.loads(RSAAlgorithm.to_jwk(weak.public_key()))
        weak_public['kid'] = 'weak'
        cases = [None, {}, {'keys': []}, {'keys': [self.public, self.public]},
                 {'keys': [weak_public]}, {'keys': [dict(self.public, use='enc')]},
                 {'keys': [dict(self.public, alg='HS256')]},
                 {'keys': [dict(self.public, key_ops=['sign'])]},
                 {'keys': [dict(self.public, d='not-a-private-key')]},
                 {'keys': [dict(self.public, x5u='https://attacker.example')]},
                 {'keys': [dict(self.public, n='invalid')]},
                 {'keys': [self.public], 'extra': 'unexpected'},
                 {'keys': [dict(self.public, padding='x' * 65537)]}]
        for value in cases:
            with self.subTest(case=str(type(value))), self.assertRaises(ValueError):
                AccessTokenVerifier(ISSUER, AUDIENCE, [CLIENT], value)

    def test_issuer_audience_and_client_configuration_is_fixed(self):
        for issuer in ('http://identity.example', 'https://user:password@identity.example', ISSUER + '?token=bad'):
            with self.assertRaises(ValueError):
                AccessTokenVerifier(issuer, AUDIENCE, [CLIENT], {'keys': [self.public]})
        for audience, clients, scope in (('', [CLIENT], 'runix:fs'), (AUDIENCE, [], 'runix:fs'),
                                         (AUDIENCE, CLIENT, 'runix:fs'), (AUDIENCE, [CLIENT], '* scope')):
            with self.assertRaises(ValueError):
                AccessTokenVerifier(ISSUER, audience, clients, {'keys': [self.public]}, scope)

    def test_signature_identity_flows_to_registry_with_fresh_role_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            box = MeteringOutbox(str(Path(directory) / 'auth.sqlite'), '999999999999', 'test-product')
            try:
                sts, metering = Mock(), Mock()
                sts.get_caller_identity.return_value = {'Account': '999999999999'}
                metering.resolve_customer.return_value = dict(CustomerAWSAccountId='123456789012',
                    LicenseArn='arn:aws:license-manager:us-east-1:999999999999:license:test',
                    ProductCode='test-product', Metadata={'AgreementId': 'agmt-test'})
                registry = RegistrationRegistry(box, RegistrationGateway(sts, metering, '999999999999', 'test-product'), ISSUER)
                registry.set_membership('org-one', 'subject-one', 'owner')
                claim = registry.register('synthetic-marketplace-token', NOW)
                # Forged JWT org/admin claims do not override the DB membership.
                token = self.token(dict(self.payload, role='admin', organization='org-other'))
                principal = self.verifier.verify(token, NOW)
                with self.assertRaises(MarketplaceDenied):
                    registry.bind(principal, 'org-other', claim, NOW)
                self.assertEqual(registry.bind(principal, 'org-one', claim, NOW)['state'], 'pending_license_verification')
                registry.set_membership('org-one', 'subject-one', None)
                with self.assertRaises(MarketplaceDenied):
                    registry.list_purchases(self.verifier.verify(token, NOW), 'org-one', NOW)
            finally:
                box.close()


if __name__ == '__main__':
    unittest.main()
