"""Trusted synthetic events and actual SDK models; no real AWS license grant."""
import copy
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import boto3
from botocore.stub import Stubber

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase, RegistrationGateway
from marketplace_agreement import AgreementReader
from marketplace_lifecycle import DEPROVISIONED, UPDATED, NegativeLifecycle
from marketplace_metering import MeteringConflict, MeteringOutbox, instant
from marketplace_payg_license import PaygLicenseState
from marketplace_registration import Principal, RegistrationRegistry

SELLER = '999999999999'
BUYER = '123456789012'
PRODUCT = 'synthetic-code'
PRODUCT_ID = 'prod-synthetic'
NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
PURCHASE = Purchase(BUYER, 'arn:aws:license-manager::999999999999:license:l-test', PRODUCT, 'agmt-synthetic')
ISSUER = 'https://issuer.example.test'
PRINCIPAL = Principal(ISSUER, 'test-subject', NOW + timedelta(minutes=15))
RESPONSE = {'agreementId': PURCHASE.agreement_id, 'agreementType': 'PurchaseAgreement',
            'acceptor': {'accountId': BUYER}, 'proposer': {'accountId': SELLER},
            'proposalSummary': {'resources': [{'id': PRODUCT_ID, 'type': 'SaaSProduct'}]},
            'status': 'ACTIVE', 'startTime': NOW - timedelta(days=1)}


def event(purchase=PURCHASE, kind=UPDATED, at=NOW - timedelta(minutes=5)):
    return {'version': '0', 'id': str(uuid.uuid4()), 'detail-type': kind,
            'source': 'aws.agreement-marketplace', 'account': SELLER, 'region': 'us-east-1',
            'time': at.isoformat(),
            'resources': ['arn:aws:aws-marketplace::aws:agreement:' + purchase.agreement_id],
            'detail': {'catalog': 'AWSMarketplace', 'agreement': {'id': purchase.agreement_id},
                       'acceptor': {'accountId': purchase.account_id}, 'proposer': {'accountId': SELLER},
                       'product': {'id': PRODUCT_ID, 'code': PRODUCT},
                       'license': {'arn': purchase.license_arn}}}


class PaygLicenseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = str(Path(self.temp.name) / 'license.sqlite')
        self.box = MeteringOutbox(self.path, SELLER, PRODUCT)
        self.addCleanup(lambda: self.box.close())
        self.sts = Mock()
        self.sts.get_caller_identity.return_value = {'Account': SELLER}
        self.metering = Mock()
        self.registry = RegistrationRegistry(self.box, RegistrationGateway(self.sts, self.metering, SELLER, PRODUCT), ISSUER)
        self.registry.set_membership('org-one', PRINCIPAL.subject, 'owner')
        self.client = boto3.client('marketplace-agreement', region_name='us-east-1',
                                  aws_access_key_id='testing', aws_secret_access_key='testing')
        self.stub = Stubber(self.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.reader = AgreementReader(self.sts, self.client, SELLER, PRODUCT, PRODUCT_ID)
        self.state = PaygLicenseState(self.box, PRODUCT_ID, self.reader)

    def bind(self, purchase=PURCHASE, org='org-one'):
        self.metering.resolve_customer.return_value = {
            'CustomerAWSAccountId': purchase.account_id, 'ProductCode': purchase.product_code,
            'LicenseArn': purchase.license_arn, 'Metadata': {'AgreementId': purchase.agreement_id}}
        claim = self.registry.register('synthetic-token', NOW)
        return self.registry.bind(PRINCIPAL, org, claim, NOW)['id']

    def response(self, purchase=PURCHASE, **changes):
        body = {**RESPONSE, 'agreementId': purchase.agreement_id, **changes}
        self.stub.add_response('describe_agreement', body, {'agreementId': purchase.agreement_id})

    def ready(self):
        self.state.record_update(event(), NOW)
        return self.bind()

    def check(self, intent):
        return self.state.check_pending(intent, clock=lambda: NOW)

    def test_matching_event_and_fresh_agreement_do_not_provision_or_meter(self):
        intent = self.ready()
        self.response()
        checked = self.check(intent)
        self.assertEqual(checked.purchase, PURCHASE)
        self.assertEqual(checked.organization_id, 'org-one')
        self.assertEqual(checked.valid_until, NOW + timedelta(seconds=30))
        self.assertEqual(self.box.db.execute('SELECT state FROM provisioning_intents').fetchone()[0],
                         'pending_license_verification')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 0)
        self.stub.assert_no_pending_responses()

    def test_outer_write_transaction_is_rejected_before_aws_read(self):
        intent = self.ready()
        with patch.object(self.reader, 'describe') as read:
            with self.box.transaction():
                with self.assertRaises(MarketplaceUnavailable):
                    self.check(intent)
            read.assert_not_called()

    def test_registration_without_update_never_reads_agreement(self):
        intent = self.bind()
        with self.assertRaises(MarketplaceDenied):
            self.check(intent)
        self.stub.assert_no_pending_responses()

    def test_update_before_registration_does_not_create_intent_or_membership(self):
        self.state.record_update(event(), NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)
        self.response()
        self.check(self.bind())

    def test_event_replay_and_changed_body_conflict(self):
        value = event()
        self.assertTrue(self.state.record_update(value, NOW))
        self.assertFalse(self.state.record_update(value, NOW))
        changed = copy.deepcopy(value)
        changed['detail']['requestId'] = 'changed'
        with self.assertRaises(MeteringConflict):
            self.state.record_update(changed, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 1)

    def test_cross_kind_id_conflict_does_not_create_a_false_stop(self):
        value = event()
        self.state.record_update(value, NOW)
        changed = copy.deepcopy(value)
        changed['detail-type'] = DEPROVISIONED
        with self.assertRaises(MeteringConflict):
            self.state.negative.apply(changed, NOW)
        self.assertIsNone(self.box.stop_info(PURCHASE.license_arn))

    def test_default_negative_reducer_still_rejects_update(self):
        with self.assertRaises(ValueError):
            self.state.negative.apply(event(), NOW)
        with self.assertRaises(ValueError):
            self.state.record_update(event(kind=DEPROVISIONED), NOW)

    def test_out_of_order_updates_are_audited_without_rewinding(self):
        latest = event(at=NOW - timedelta(seconds=1))
        self.state.record_update(latest, NOW)
        self.state.record_update(event(at=NOW - timedelta(seconds=100)), NOW)
        self.state.record_update(event(at=NOW - timedelta(seconds=1)), NOW)
        row = self.box.db.execute('SELECT updated,event_id FROM payg_license_updates').fetchone()
        self.assertEqual(tuple(row), (instant(NOW) - 1, latest['id']))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 3)

    def test_foreign_malformed_future_and_missing_identity_events_denied(self):
        mutations = [(['account'], BUYER), (['source'], 'foreign'), (['region'], 'us-west-2'),
                     (['id'], 'bad'), (['time'], (NOW + timedelta(seconds=1)).isoformat()),
                     (['resources'], []), (['detail', 'catalog'], 'foreign'),
                     (['detail', 'product', 'id'], 'prod-other'), (['detail', 'product', 'code'], 'other'),
                     (['detail', 'acceptor', 'accountId'], 'bad'), (['detail', 'proposer', 'accountId'], BUYER),
                     (['detail', 'license', 'arn'], 'bad'), (['detail', 'agreement', 'id'], 'bad?query')]
        for path, replacement in mutations:
            value = event()
            target = value
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path), self.assertRaises((MarketplaceDenied, ValueError)):
                self.state.record_update(value, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM payg_license_updates').fetchone()[0], 0)

    def test_license_identity_cannot_be_rebound_by_later_update(self):
        self.state.record_update(event(), NOW)
        for purchase in (replace(PURCHASE, account_id='111111111111'),
                         replace(PURCHASE, agreement_id='agmt-other')):
            with self.assertRaises(MeteringConflict):
                self.state.record_update(event(purchase), NOW)

    def test_stop_before_or_after_update_always_wins(self):
        intent = self.bind()
        self.state.negative.apply(event(kind=DEPROVISIONED), NOW)
        self.state.record_update(event(), NOW)
        self.state.record_update(event(at=NOW), NOW)
        with self.assertRaises(MarketplaceDenied):
            self.check(intent)
        self.assertIsNotNone(self.box.stop_info(PURCHASE.license_arn))

    def test_agreement_tombstone_also_blocks_a_later_license_update(self):
        intent = self.ready()
        ended = event(kind='Purchase Agreement Ended - Proposer')
        ended['detail']['agreement']['status'] = 'CANCELLED'
        self.state.negative.apply(ended, NOW)
        self.state.record_update(event(at=NOW), NOW)
        with self.assertRaises(MarketplaceDenied):
            self.check(intent)

    def test_concurrent_update_and_stop_cannot_resurrect_a_purchase(self):
        intent = self.bind()
        barrier = threading.Barrier(2)
        def apply(negative):
            box = MeteringOutbox(self.path, SELLER, PRODUCT)
            try:
                state = PaygLicenseState(box, PRODUCT_ID)
                barrier.wait(timeout=5)
                return (state.negative.apply(event(kind=DEPROVISIONED), NOW) if negative
                        else state.record_update(event(), NOW))
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(list(pool.map(apply, (False, True))), [True, True])
        with self.assertRaises(MarketplaceDenied):
            self.check(intent)

    def test_binding_change_during_verification_denies_old_context(self):
        intent = self.ready()
        self.response()
        describe = self.reader.describe
        def changed(purchase, now):
            observation = describe(purchase, now)
            with self.box.transaction():
                self.box.db.execute("UPDATE org_purchases SET org='org-other'")
                self.box.db.execute("UPDATE provisioning_intents SET org='org-other'")
            return observation
        with patch.object(self.reader, 'describe', side_effect=changed), self.assertRaises(MarketplaceDenied):
            self.check(intent)

    def test_invalid_clock_or_check_before_recorded_update_never_calls_aws(self):
        intent = self.ready()
        with self.assertRaises(ValueError):
            self.state.check_pending(intent, clock=lambda: NOW.replace(tzinfo=None))
        with self.assertRaises(MarketplaceDenied):
            self.state.check_pending(intent, clock=lambda: NOW - timedelta(minutes=10))

    def test_cancellation_during_aws_call_is_committed_without_lock_and_denies(self):
        intent = self.ready()
        self.response()
        describe = self.reader.describe
        def stop():
            box = MeteringOutbox(self.path, SELLER, PRODUCT)
            try:
                NegativeLifecycle(box, PRODUCT_ID).apply(event(kind=DEPROVISIONED), NOW)
            finally:
                box.close()
        def during(purchase, now):
            self.assertFalse(self.box.db.in_transaction)
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(stop).result(timeout=3)
            return describe(purchase, now)
        with patch.object(self.reader, 'describe', side_effect=during), self.assertRaises(MarketplaceDenied):
            self.check(intent)

    def test_two_licenses_under_one_account_are_independent(self):
        first = self.ready()
        other = replace(PURCHASE, license_arn=PURCHASE.license_arn + '2', agreement_id='agmt-other')
        self.state.record_update(event(other), NOW)
        second = self.bind(other)
        self.state.negative.apply(event(kind=DEPROVISIONED), NOW)
        with self.assertRaises(MarketplaceDenied):
            self.check(first)
        self.response(other)
        self.assertEqual(self.check(second).purchase, other)

    def test_unauthorized_org_binding_and_unknown_intents_cannot_qualify(self):
        self.state.record_update(event(), NOW)
        with self.assertRaises(MarketplaceDenied):
            self.bind(org='org-other')
        for intent in (None, 'bad', '0' * 32):
            with self.assertRaises(MarketplaceDenied):
                self.check(intent)

    def test_inactive_future_and_elapsed_agreement_denied(self):
        intent = self.ready()
        for mutation in ({'status': 'CANCELLED'}, {'startTime': NOW + timedelta(seconds=1)},
                         {'endTime': NOW}):
            self.response(**mutation)
            with self.assertRaises(MarketplaceDenied):
                self.check(intent)

    def test_agreement_identity_substitution_and_rotated_seller_denied(self):
        intent = self.ready()
        self.response(acceptor={'accountId': SELLER})
        with self.assertRaises(MarketplaceDenied):
            self.check(intent)
        self.sts.get_caller_identity.return_value = {'Account': BUYER}
        with self.assertRaises(MarketplaceDenied):
            self.check(intent)

    def test_sdk_error_never_becomes_success_and_does_not_leak(self):
        intent = self.ready()
        self.stub.add_client_error('describe_agreement', service_error_code='AccessDeniedException',
                                   service_message='private-response', expected_params={'agreementId': PURCHASE.agreement_id})
        with self.assertRaises(MarketplaceUnavailable) as caught:
            self.check(intent)
        self.assertNotIn('private', str(caught.exception))

    def test_missing_verifier_is_explicit_unavailable(self):
        intent = self.ready()
        with self.assertRaises(MarketplaceUnavailable):
            PaygLicenseState(self.box, PRODUCT_ID).check_pending(intent, clock=lambda: NOW)

    def test_clock_regression_and_slow_verification_fail(self):
        intent = self.ready()
        for finish in (NOW - timedelta(seconds=1), NOW + timedelta(seconds=30)):
            self.response()
            times = iter((NOW, finish))
            with self.assertRaises(MarketplaceUnavailable):
                self.state.check_pending(intent, clock=lambda: next(times))

    def test_agreement_expires_during_call_and_short_end_caps_check(self):
        intent = self.ready()
        self.response(endTime=NOW + timedelta(seconds=2))
        times = iter((NOW, NOW + timedelta(seconds=2)))
        with self.assertRaises(MarketplaceDenied):
            self.state.check_pending(intent, clock=lambda: next(times))
        self.response(endTime=NOW + timedelta(seconds=10))
        self.assertEqual(self.check(intent).valid_until, NOW + timedelta(seconds=10))

    def test_duplicate_concurrent_events_commit_once(self):
        value = event()
        def apply(_):
            box = MeteringOutbox(self.path, SELLER, PRODUCT)
            try:
                return PaygLicenseState(box, PRODUCT_ID).record_update(value, NOW)
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            outcomes = list(pool.map(apply, range(8)))
        self.assertEqual(sum(outcomes), 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 1)

    def test_audit_insert_failure_rolls_back_identity_and_update(self):
        self.box.db.execute("CREATE TEMP TRIGGER fail_event BEFORE INSERT ON lifecycle_events BEGIN SELECT RAISE(ABORT,'synthetic'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.state.record_update(event(), NOW)
        for table in ('licenses', 'payg_license_updates', 'lifecycle_events'):
            self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)

    def test_process_exit_preserves_committed_event(self):
        code = '''import json,os,sys
from datetime import datetime
from marketplace_metering import MeteringOutbox
from marketplace_payg_license import PaygLicenseState
box=MeteringOutbox(sys.argv[1],sys.argv[2],sys.argv[3])
PaygLicenseState(box,sys.argv[4]).record_update(json.loads(sys.argv[5]),datetime.fromisoformat(sys.argv[6]))
os._exit(0)
'''
        environment = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parent)}
        subprocess.run([sys.executable, '-c', code, self.path, SELLER, PRODUCT, PRODUCT_ID,
                        json.dumps(event()), NOW.isoformat()], env=environment, check=True, timeout=15)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM payg_license_updates').fetchone()[0], 1)
        self.response()
        self.check(self.bind())

    def test_mismatched_verifier_configuration_is_rejected(self):
        for field, value in (('seller_account', BUYER), ('product_code', 'other'), ('product_id', 'prod-other')):
            reader = Mock(seller_account=SELLER, product_code=PRODUCT, product_id=PRODUCT_ID)
            setattr(reader, field, value)
            with self.subTest(field=field), self.assertRaises(ValueError):
                PaygLicenseState(self.box, PRODUCT_ID, reader)


if __name__ == '__main__':
    unittest.main()
