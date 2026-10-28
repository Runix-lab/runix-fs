"""Trusted negative-event fixtures; not evidence of live AWS event provenance."""
import copy
import dataclasses
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from marketplace_adapter import MarketplaceDenied, Purchase, RegistrationGateway
from marketplace_lifecycle import NegativeLifecycle
from marketplace_metering import MeteringConflict, MeteringOutbox, MeteringWorker
from marketplace_registration import Principal, RegistrationRegistry
from marketplace_storage_usage import StorageUsageLedger, DIMENSION

UTC = timezone.utc
START = datetime(2026, 10, 28, 1, tzinfo=UTC)
NOW = START + timedelta(hours=1)
SELLER = '999999999999'
PRODUCT_ID = 'prod-synthetic'
PURCHASE = Purchase('123456789012', 'arn:aws:license-manager:us-east-1:999999999999:license:synthetic', 'synthetic-code', 'agmt-synthetic')
ISSUER = 'https://issuer.example.test'
PRINCIPAL = Principal(ISSUER, 'subject-synthetic', NOW + timedelta(minutes=15))


def event(purchase=PURCHASE, license_event=False, at=NOW, event_id=None):
    result = {
        'version': '0', 'id': event_id or str(uuid.uuid4()),
        'detail-type': 'License Deprovisioned - Manufacturer' if license_event else 'Purchase Agreement Ended - Proposer',
        'source': 'aws.agreement-marketplace', 'account': SELLER, 'region': 'us-east-1',
        'time': at.isoformat(),
        'resources': ['arn:aws:aws-marketplace::aws:agreement:' + purchase.agreement_id],
        'detail': {
            'catalog': 'AWSMarketplace',
            'agreement': {'id': purchase.agreement_id, 'status': 'CANCELLED'},
            'acceptor': {'accountId': purchase.account_id}, 'proposer': {'accountId': SELLER},
        },
    }
    if license_event:
        result['detail'].update(product={'id': PRODUCT_ID, 'code': PURCHASE.product_code},
                                license={'arn': purchase.license_arn})
    return result


class NegativeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'lifecycle.sqlite')
        self.box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
        self.reducer = NegativeLifecycle(self.box, PRODUCT_ID)

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def enqueue(self, purchase=PURCHASE, quantity=2):
        return self.box.enqueue(purchase, DIMENSION, START, quantity, NOW)

    def registry(self):
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        client = Mock()
        client.resolve_customer.return_value = dict(CustomerAWSAccountId=PURCHASE.account_id,
            LicenseArn=PURCHASE.license_arn, ProductCode=PURCHASE.product_code,
            Metadata={'AgreementId': PURCHASE.agreement_id})
        registry = RegistrationRegistry(self.box, RegistrationGateway(sts, client, SELLER, PURCHASE.product_code), ISSUER)
        registry.set_membership('org-one', PRINCIPAL.subject, 'owner')
        return registry

    def test_stop_quarantines_pending_and_sending_without_deleting_history(self):
        pending = self.enqueue()
        sending = self.enqueue(dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + '2'))
        batch = self.box.claim(NOW)
        self.assertEqual(len(batch.rows), 2)
        self.reducer.apply(event(), NOW)
        self.assertFalse(self.box.ready(batch, NOW))
        self.assertFalse(self.box.claim(NOW).rows)
        for key in (pending, sending):
            self.assertEqual(self.box.inspect(key)['state'], 'quarantined')
            self.assertEqual(self.box.inspect(key)['reason'], 'lifecycle_stop_reconcile')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM licenses').fetchone()[0], 2)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 2)

    def test_accepted_record_id_is_preserved_after_stop(self):
        key = self.enqueue()
        batch = self.box.claim(NOW)
        self.box.finish(batch, {'Results': [dict(UsageRecord=batch.records[0], Status='Success', MeteringRecordId='prior-accepted')]}, NOW)
        self.reducer.apply(event(), NOW)
        self.assertEqual(self.box.inspect(key)['state'], 'accepted')
        self.assertEqual(self.box.inspect(key)['record_id'], 'prior-accepted')
        with self.assertRaises(MarketplaceDenied):
            self.enqueue()

    def test_duplicate_and_changed_body_replay(self):
        value = event()
        self.assertTrue(self.reducer.apply(value, NOW))
        self.assertFalse(self.reducer.apply(value, NOW + timedelta(seconds=1)))
        changed = copy.deepcopy(value)
        changed['detail']['agreement']['status'] = 'EXPIRED'
        with self.assertRaises(MeteringConflict):
            self.reducer.apply(changed, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 1)

    def test_late_events_only_tighten_stop_boundary(self):
        self.reducer.apply(event(at=NOW - timedelta(seconds=10)), NOW)
        self.reducer.apply(event(at=NOW), NOW)
        self.enqueue_identity_only()
        self.assertEqual(self.box.stop_info(PURCHASE.license_arn)['cutoff'], int((NOW - timedelta(seconds=10)).timestamp()))
        self.reducer.apply(event(at=NOW - timedelta(seconds=20)), NOW)
        self.assertEqual(self.box.stop_info(PURCHASE.license_arn)['cutoff'], int((NOW - timedelta(seconds=20)).timestamp()))

    def enqueue_identity_only(self):
        with self.box.transaction():
            self.box.bind_purchase(PURCHASE)

    def test_license_stop_affects_only_one_license_agreement_stop_affects_all(self):
        first = self.enqueue()
        other = dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + '2')
        second = self.enqueue(other)
        self.reducer.apply(event(license_event=True), NOW)
        self.assertEqual(self.box.inspect(first)['state'], 'quarantined')
        self.assertEqual(self.box.inspect(second)['state'], 'pending')
        self.reducer.apply(event(), NOW)
        self.assertEqual(self.box.inspect(second)['state'], 'quarantined')

    def test_new_agreement_same_buyer_is_not_stopped(self):
        self.enqueue()
        self.reducer.apply(event(), NOW)
        new = dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + '2', agreement_id='agmt-renewal')
        key = self.enqueue(new)
        self.assertEqual(self.box.inspect(key)['state'], 'pending')

    def test_stop_before_registration_blocks_later_claim(self):
        registry = self.registry()
        self.reducer.apply(event(), NOW)
        with self.assertRaises(MarketplaceDenied):
            registry.register('synthetic-token', NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM registration_claims').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 0)

    def test_license_stop_before_identity_is_retained_and_not_rebound(self):
        self.reducer.apply(event(license_event=True), NOW)
        with self.assertRaises(MarketplaceDenied):
            self.enqueue()
        with self.assertRaises(MeteringConflict), self.box.transaction():
            self.box.bind_purchase(dataclasses.replace(PURCHASE, account_id='888888888888'))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM license_stops').fetchone()[0], 1)

    def test_existing_claim_and_binding_do_not_reopen_after_stop(self):
        registry = self.registry()
        claim = registry.register('synthetic-token', NOW)
        registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        self.reducer.apply(event(), NOW)
        with self.assertRaises(MarketplaceDenied):
            registry.bind(PRINCIPAL, 'org-one', claim, NOW)
        result = registry.list_purchases(PRINCIPAL, 'org-one', NOW)
        self.assertEqual(result[0]['state'], 'stopped_reconciliation')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM org_purchases').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_intents').fetchone()[0], 1)

    def test_stop_rejects_new_usage_activation_append_and_seal(self):
        ledger = StorageUsageLedger(self.box)
        ledger.activate(PURCHASE, START, START)
        ledger.append(PURCHASE, 'known-interval', START, NOW, 1 << 30, NOW)
        self.reducer.apply(event(), NOW)
        for operation in (
            lambda: ledger.activate(PURCHASE, START, NOW),
            lambda: ledger.append(PURCHASE, 'new', NOW, NOW + timedelta(seconds=1), 1, NOW + timedelta(seconds=1)),
            lambda: ledger.seal(PURCHASE, NOW, NOW, final=True),
        ):
            with self.assertRaises(MarketplaceDenied):
                operation()
        self.assertFalse(ledger.append(PURCHASE, 'known-interval', START, NOW, 1 << 30, NOW))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM storage_intervals').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 0)

    def test_inflight_sdk_success_is_audited_and_does_not_undo_stop(self):
        key = self.enqueue()
        client, sts = Mock(), Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        def remote(**parameters):
            self.reducer.apply(event(), NOW)
            return {'Results': [dict(UsageRecord=parameters['UsageRecords'][0], Status='Success', MeteringRecordId='inflight-accepted')]}
        client.batch_meter_usage.side_effect = remote
        self.assertEqual(MeteringWorker(self.box, sts, client).dispatch(lambda: NOW), 0)
        self.assertEqual(self.box.inspect(key)['state'], 'quarantined')
        audit = self.box.db.execute('SELECT outcomes FROM responses').fetchone()[0]
        self.assertIn('inflight-accepted', audit)
        self.assertFalse(self.box.claim(NOW).rows)

    def test_stop_during_claim_prevents_any_sdk_call(self):
        self.enqueue()
        times = iter([NOW, NOW])
        count = 0
        def clock():
            nonlocal count
            count += 1
            if count == 2:
                self.reducer.apply(event(), NOW)
            return next(times)
        client, sts = Mock(), Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        self.assertEqual(MeteringWorker(self.box, sts, client).dispatch(clock), 0)
        client.batch_meter_usage.assert_not_called()

    def test_foreign_envelopes_products_resources_and_identities_fail(self):
        self.enqueue()
        mutations = [
            lambda e: e.update(source='custom.untrusted'),
            lambda e: e.update(account='111111111111'),
            lambda e: e.update(region='us-west-2'),
            lambda e: e.update(resources=[]),
            lambda e: e['detail'].update(catalog='foreign'),
            lambda e: e['detail']['proposer'].update(accountId='111111111111'),
            lambda e: e['detail']['acceptor'].update(accountId='888888888888'),
            lambda e: e['detail']['product'].update(id='prod-other'),
            lambda e: e['detail']['product'].update(code='other'),
            lambda e: e['detail']['license'].update(arn='not-an-arn'),
        ]
        for mutate in mutations:
            value = event(license_event=True)
            mutate(value)
            with self.subTest(value=value['id']), self.assertRaises((MarketplaceDenied, ValueError)):
                self.reducer.apply(value, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM agreement_stops').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM license_stops').fetchone()[0], 0)

    def test_wrong_agreement_buyer_does_not_create_tombstone(self):
        self.enqueue()
        wrong = event(dataclasses.replace(PURCHASE, account_id='888888888888'))
        with self.assertRaises(MarketplaceDenied):
            self.reducer.apply(wrong, NOW)
        self.assertIsNone(self.box.stop_info(PURCHASE.license_arn))

    def test_malformed_and_positive_events_never_activate_or_stop(self):
        for field, value in (('detail-type', 'License Updated - Manufacturer'), ('detail-type', []),
                             ('time', 'not-a-date'), ('time', '2026-10-28T02:00:00'),
                             ('id', 'not-an-id'), ('version', '1'), ('detail', None)):
            item = event()
            item[field] = value
            with self.assertRaises((MarketplaceDenied, ValueError)):
                self.reducer.apply(item, NOW)
        with self.assertRaises(ValueError):
            self.reducer.apply(event(at=NOW + timedelta(seconds=1)), NOW)
        item = event()
        item['detail']['agreement']['status'] = 'ACTIVE'
        with self.assertRaises(ValueError):
            self.reducer.apply(item, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)

    def test_expiry_end_time_is_earlier_than_receipt_and_fraction_is_conservative(self):
        self.enqueue_identity_only()
        item = event(at=NOW.replace(microsecond=900000))
        item['detail']['agreement']['endTime'] = (NOW - timedelta(minutes=10)).isoformat()
        item['detail']['agreement']['status'] = 'EXPIRED'
        self.reducer.apply(item, NOW)
        self.assertEqual(self.box.stop_info(PURCHASE.license_arn)['cutoff'], int((NOW - timedelta(minutes=10)).timestamp()))

    def test_quarantine_failure_rolls_back_event_and_stop_then_retry(self):
        key = self.enqueue()
        item = event()
        self.box.db.execute("CREATE TRIGGER fail_stop BEFORE UPDATE OF state ON usage WHEN NEW.reason='lifecycle_stop_reconcile' BEGIN SELECT RAISE(ABORT, 'fault'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.reducer.apply(item, NOW)
        self.assertIsNone(self.box.stop_info(PURCHASE.license_arn))
        self.assertEqual(self.box.inspect(key)['state'], 'pending')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)
        self.box.db.execute('DROP TRIGGER fail_stop')
        self.reducer.apply(item, NOW)
        self.assertEqual(self.box.inspect(key)['state'], 'quarantined')

    def test_concurrent_enqueue_and_stop_leave_no_dispatchable_usage(self):
        barrier = threading.Barrier(2)
        item = event()
        def operation(stop):
            box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
            reducer = NegativeLifecycle(box, PRODUCT_ID)
            try:
                barrier.wait(timeout=5)
                if stop:
                    return reducer.apply(item, NOW)
                try:
                    return box.enqueue(PURCHASE, DIMENSION, START, 2, NOW)
                except MarketplaceDenied:
                    return 'denied'
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(operation, [False, True]))
        self.assertFalse(self.box.claim(NOW).rows)
        states = [r[0] for r in self.box.db.execute('SELECT state FROM usage')]
        self.assertTrue(all(state == 'quarantined' for state in states))

    def test_stop_survives_process_exit_before_registration(self):
        item = event()
        code = '''import json,os
from datetime import datetime,timezone
from marketplace_metering import MeteringOutbox
from marketplace_lifecycle import NegativeLifecycle
b=MeteringOutbox(os.environ['TEST_DB'],'999999999999','synthetic-code')
NegativeLifecycle(b,'prod-synthetic').apply(json.loads(os.environ['TEST_EVENT']),datetime(2026,10,28,2,tzinfo=timezone.utc))
os._exit(0)
'''
        subprocess.run([sys.executable, '-c', code], check=True,
            env=dict(os.environ, TEST_DB=self.path, TEST_EVENT=json.dumps(item), PYTHONPATH=str(Path(__file__).parent.resolve())))
        self.assertFalse(self.reducer.apply(item, NOW))
        with self.assertRaises(MarketplaceDenied):
            self.enqueue()

    def test_product_configuration_is_immutable(self):
        with self.assertRaises(MeteringConflict):
            NegativeLifecycle(self.box, 'prod-other')
        with self.assertRaises(ValueError):
            NegativeLifecycle(self.box, 'not-a-product-id')

    def test_guard_denies_agreement_before_any_local_identity_row_exists(self):
        self.reducer.apply(event(), NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM licenses').fetchone()[0], 0)
        with self.assertRaises(MarketplaceDenied):
            self.box.assert_not_stopped(PURCHASE)


if __name__ == '__main__':
    unittest.main()
