"""Pending organization bindings; principals are trusted test fixtures, not SSO."""
import dataclasses
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, call

import boto3
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase, RegistrationGateway
from marketplace_metering import MeteringConflict, MeteringOutbox
from marketplace_registration import Principal, RegistrationRegistry

NOW = datetime(2026, 10, 27, 3, tzinfo=timezone.utc)
ISSUER = 'https://identity.example.test'
SELLER = '999999999999'
PURCHASE = Purchase('123456789012', 'arn:aws:license-manager:us-east-1:999999999999:license:test-registration', 'test-product', 'test-agreement')
PRINCIPAL = Principal(ISSUER, 'subject-test', NOW + timedelta(minutes=15))
RESOLVED = dict(CustomerAWSAccountId=PURCHASE.account_id, LicenseArn=PURCHASE.license_arn,
                ProductCode=PURCHASE.product_code, Metadata={'AgreementId': PURCHASE.agreement_id})


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'registry.sqlite')
        self.box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
        self.metering = Mock()
        self.metering.resolve_customer.return_value = RESOLVED
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        self.gateway = RegistrationGateway(sts, self.metering, SELLER, PURCHASE.product_code)
        self.registry = RegistrationRegistry(self.box, self.gateway, ISSUER)
        self.registry.set_membership('org-one', PRINCIPAL.subject, 'owner')

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def claim(self):
        return self.registry.register('synthetic-aws-token', NOW)

    def test_sdk_resolver_has_no_contract_entitlement_dependency(self):
        client = boto3.client('meteringmarketplace', region_name='us-east-1', aws_access_key_id='test-only', aws_secret_access_key='test-only')
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        with Stubber(client) as stub:
            stub.add_response('resolve_customer', RESOLVED, {'RegistrationToken': 'test-token'})
            gateway = RegistrationGateway(sts, client, SELLER, PURCHASE.product_code)
            self.assertEqual(gateway.resolve_registration('test-token'), PURCHASE)
            self.assertFalse(hasattr(gateway, 'entitlements'))
            self.assertFalse(hasattr(gateway, 'contract_quantity'))
            stub.assert_no_pending_responses()

    def test_session_factory_only_creates_registration_clients(self):
        session = Mock()
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        session.client.side_effect = [sts, self.metering]
        gateway = RegistrationGateway.from_session(session, SELLER, PURCHASE.product_code)
        self.assertEqual(gateway.seller_account, SELLER)
        self.assertEqual(session.client.call_args_list, [call('sts', region_name='us-east-1'), call('meteringmarketplace', region_name='us-east-1')])

    def test_wrong_seller_and_product_deny_before_persistence(self):
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': '111111111111'}
        with self.assertRaises(MarketplaceDenied):
            RegistrationGateway(sts, self.metering, SELLER, PURCHASE.product_code)
        self.metering.resolve_customer.return_value = dict(RESOLVED, ProductCode='wrong')
        with self.assertRaises(MarketplaceDenied):
            self.claim()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 0)

    def test_missing_or_invalid_purchase_metadata_deny(self):
        for result in ({}, dict(RESOLVED, Metadata={}), dict(RESOLVED, Metadata=None),
                       dict(RESOLVED, LicenseArn='bad'), dict(RESOLVED, CustomerAWSAccountId='wrong')):
            self.metering.resolve_customer.return_value = result
            with self.assertRaises(MarketplaceDenied):
                self.claim()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM licenses').fetchone()[0], 0)

    def test_sdk_transport_failure_stores_no_pending_claim(self):
        self.metering.resolve_customer.side_effect = EndpointConnectionError(endpoint_url='https://example.invalid')
        with self.assertRaises(MarketplaceUnavailable):
            self.claim()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 0)

    def test_raw_tokens_and_claims_are_not_persisted(self):
        claim = self.claim()
        dump = '\n'.join(self.box.db.iterdump())
        self.assertNotIn('synthetic-aws-token', dump)
        self.assertNotIn(claim, dump)
        self.assertEqual(len(claim), 43)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 0)

    def test_bind_is_idempotent_and_does_not_provision(self):
        claim = self.claim()
        first = self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        second = self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        third = self.registry.bind(PRINCIPAL, 'org-one', self.claim(), NOW)
        self.assertEqual(first, second)
        self.assertEqual(first, third)
        self.assertEqual(first['state'], 'pending_license_verification')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 0)

    def test_cross_organization_claim_replay_denied(self):
        claim = self.claim()
        self.registry.set_membership('org-two', PRINCIPAL.subject, 'admin')
        self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        with self.assertRaises(MarketplaceDenied):
            self.registry.bind(PRINCIPAL, 'org-two', claim, NOW)
        self.assertFalse(self.registry.list_purchases(PRINCIPAL, 'org-two', NOW))

    def test_anonymous_wrong_issuer_expired_and_invalid_context(self):
        claim = self.claim()
        for principal in (None, 'subject-test', dataclasses.replace(PRINCIPAL, issuer='https://attacker.example'),
                          dataclasses.replace(PRINCIPAL, expires_at=NOW),
                          dataclasses.replace(PRINCIPAL, expires_at=NOW + timedelta(hours=1)),
                          dataclasses.replace(PRINCIPAL, subject=''),
                          dataclasses.replace(PRINCIPAL, expires_at=NOW.replace(tzinfo=None))):
            with self.subTest(principal=type(principal).__name__), self.assertRaises(MarketplaceDenied):
                self.registry.bind(principal, 'org-one', claim, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)

    def test_member_can_read_own_org_but_not_bind_and_revocation_applies(self):
        claim = self.claim()
        self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        member = dataclasses.replace(PRINCIPAL, subject='member-test')
        self.registry.set_membership('org-one', member.subject, 'member')
        self.assertEqual(len(self.registry.list_purchases(member, 'org-one', NOW)), 1)
        with self.assertRaises(MarketplaceDenied):
            self.registry.bind(member, 'org-one', claim, NOW)
        with self.assertRaises(MarketplaceDenied):
            self.registry.list_purchases(member, 'org-other', NOW)
        self.registry.set_membership('org-one', member.subject, None)
        with self.assertRaises(MarketplaceDenied):
            self.registry.list_purchases(member, 'org-one', NOW)
        self.registry.set_membership('org-one', PRINCIPAL.subject, None)
        with self.assertRaises(MarketplaceDenied):
            self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)

    def test_expired_unknown_malformed_and_future_claims_deny(self):
        claim = self.claim()
        for token, now in ((claim, NOW + timedelta(seconds=600)), ('A' * 43, NOW),
                           ('', NOW), ('../not-a-token', NOW), (None, NOW),
                           (claim, NOW - timedelta(seconds=1))):
            with self.assertRaises(MarketplaceDenied):
                self.registry.bind(PRINCIPAL, 'org-one', token, now)

    def test_immutable_identity_cannot_be_rebound_on_new_callback(self):
        self.claim()
        self.metering.resolve_customer.return_value = dict(RESOLVED, CustomerAWSAccountId='888888888888')
        with self.assertRaises(MeteringConflict):
            self.claim()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 1)

    def test_two_agreements_for_same_account_have_separate_bindings(self):
        self.registry.bind(PRINCIPAL, 'org-one', self.claim(), NOW)
        self.metering.resolve_customer.return_value = dict(RESOLVED, LicenseArn=PURCHASE.license_arn + '-2', Metadata={'AgreementId': 'agreement-2'})
        self.registry.bind(PRINCIPAL, 'org-one', self.claim(), NOW)
        self.assertEqual(len(self.registry.list_purchases(PRINCIPAL, 'org-one', NOW)), 2)

    def test_concurrent_different_org_bind_has_one_winner_and_one_intent(self):
        claim = self.claim()
        self.registry.set_membership('org-two', PRINCIPAL.subject, 'owner')
        def bind(org):
            box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
            registry = RegistrationRegistry(box, self.gateway, ISSUER)
            try:
                return registry.bind(PRINCIPAL, org, claim, NOW)['org']
            except MarketplaceDenied:
                return 'denied'
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(bind, ['org-one', 'org-two']))
        self.assertEqual(results.count('denied'), 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 1)

    def test_failure_after_binding_rolls_back_all_then_retry_succeeds(self):
        claim = self.claim()
        self.box.db.execute("CREATE TRIGGER fail_intent BEFORE INSERT ON provisioning_intents BEGIN SELECT RAISE(ABORT, 'injected'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        self.assertFalse(self.registry.list_purchases(PRINCIPAL, 'org-one', NOW))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)
        self.box.db.execute('DROP TRIGGER fail_intent')
        self.assertEqual(self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)['state'], 'pending_license_verification')

    def test_binding_survives_process_exit_without_duplicate_intent(self):
        claim = self.claim()
        code = '''import os
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock
from marketplace_adapter import RegistrationGateway
from marketplace_metering import MeteringOutbox
from marketplace_registration import Principal,RegistrationRegistry
now=datetime(2026,10,27,3,tzinfo=timezone.utc)
sts=Mock();sts.get_caller_identity.return_value={'Account':'999999999999'}
g=RegistrationGateway(sts,Mock(),'999999999999','test-product')
b=MeteringOutbox(os.environ['TEST_DB'],'999999999999','test-product')
r=RegistrationRegistry(b,g,'https://identity.example.test')
r.bind(Principal('https://identity.example.test','subject-test',now+timedelta(minutes=15)),'org-one',os.environ['TEST_CLAIM'],now)
os._exit(0)
'''
        subprocess.run([sys.executable, '-c', code], check=True, env=dict(os.environ,
                       TEST_DB=self.path, TEST_CLAIM=claim, PYTHONPATH=str(Path(__file__).parent.resolve())))
        first = self.registry.list_purchases(PRINCIPAL, 'org-one', NOW)
        self.registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        self.assertEqual(self.registry.list_purchases(PRINCIPAL, 'org-one', NOW), first)
        self.assertEqual(len(first), 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 1)

    def test_configuration_and_parameters_fail_closed(self):
        for issuer in ('http://identity.example', 'https://user:password@identity.example', 'https://identity.example?token=x'):
            with self.assertRaises(ValueError):
                RegistrationRegistry(self.box, self.gateway, issuer)
        with self.assertRaises(MeteringConflict):
            RegistrationRegistry(self.box, self.gateway, ISSUER + '/changed')
        other = Mock(product_code=PURCHASE.product_code, seller_account='888888888888')
        with self.assertRaises(ValueError):
            RegistrationRegistry(self.box, other, ISSUER)
        for org, subject, role in (('', 'test', 'owner'), ('org-one', '', 'owner'), ('org-one', 'test', 'superadmin')):
            with self.assertRaises(ValueError):
                self.registry.set_membership(org, subject, role)
        for ttl in (True, 0, 901, 0.5):
            with self.assertRaises(ValueError):
                self.registry.register('token', NOW, ttl)


if __name__ == '__main__':
    unittest.main()
