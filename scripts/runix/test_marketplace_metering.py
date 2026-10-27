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
from unittest.mock import Mock

import boto3
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber

from marketplace_adapter import MarketplaceDenied, Purchase
from marketplace_metering import (
    MeteringConflict, MeteringOutbox, MeteringProtocolError, MeteringWorker,
)

UTC = timezone.utc
START = datetime(2026, 10, 26, 1, tzinfo=UTC)
NOW = START + timedelta(hours=1)
PURCHASE = Purchase('123456789012', 'arn:aws:license-manager:us-east-1:999999999999:license:lic-test', 'test-product', 'agreement-test')
SELLER = '999999999999'


class MeteringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'metering.sqlite')
        self.box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def enqueue(self, purchase=PURCHASE, timestamp=START, quantity=1, **kwargs):
        return self.box.enqueue(purchase, 'storage_gib_hour', timestamp, quantity, kwargs.pop('now', NOW), **kwargs)

    def result(self, batch, index=0, status='Success'):
        return {'UsageRecord': batch.records[index], 'Status': status, 'MeteringRecordId': 'record-test'}

    def worker(self, client):
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        return MeteringWorker(self.box, sts, client)

    def sdk(self):
        return boto3.client('meteringmarketplace', region_name='us-east-1',
                            aws_access_key_id='test-only', aws_secret_access_key='test-only')

    def test_replay_and_immutable_conflicts(self):
        key = self.enqueue()
        self.assertEqual(key, self.enqueue())
        for change in ({'quantity': 2}, {'timestamp': START + timedelta(seconds=1)},
                       {'purchase': dataclasses.replace(PURCHASE, account_id='888888888888')},
                       {'purchase': dataclasses.replace(PURCHASE, agreement_id='another-agreement')}):
            with self.subTest(change=change), self.assertRaises(MeteringConflict):
                self.enqueue(**change)
        self.assertEqual(self.box.inspect(key)['state'], 'pending')

    def test_two_licenses_same_customer_are_separate(self):
        first = self.enqueue()
        second = self.enqueue(dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + '2'))
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.box.claim(NOW).records), 2)

    def test_license_identity_cannot_change_in_other_hour_or_dimension(self):
        self.enqueue()
        changed = dataclasses.replace(PURCHASE, account_id='888888888888')
        with self.assertRaises(MeteringConflict):
            self.box.enqueue(changed, 'other_dimension', NOW, 1, NOW)
        changed = dataclasses.replace(PURCHASE, agreement_id='other-agreement')
        with self.assertRaises(MeteringConflict):
            self.enqueue(changed, timestamp=NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 1)

    def test_reject_bad_identity_and_values(self):
        for purchase in (dataclasses.replace(PURCHASE, product_code='wrong'),
                         dataclasses.replace(PURCHASE, account_id='buyer-supplied-name'),
                         dataclasses.replace(PURCHASE, license_arn='not-an-arn')):
            with self.assertRaises(MarketplaceDenied):
                self.enqueue(purchase)
        for quantity in (-1, 2147483648, True, 0.5, '1', None):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                self.enqueue(quantity=quantity)
        for timestamp in (START.replace(tzinfo=None), START.replace(microsecond=1), NOW + timedelta(seconds=1)):
            with self.assertRaises(ValueError):
                self.enqueue(timestamp=timestamp)
        with self.assertRaises(ValueError):
            self.box.enqueue(PURCHASE, 'bad dimension', START, 1, NOW)

    def test_zero_is_valid_and_offset_normalized(self):
        key = self.enqueue(quantity=0)
        local = START.astimezone(timezone(timedelta(hours=8)))
        self.assertEqual(key, self.enqueue(timestamp=local, quantity=0))
        self.assertEqual(self.box.claim(NOW).records[0]['Timestamp'], START)

    def test_database_configuration_is_bound(self):
        for seller, product in (('888888888888', PURCHASE.product_code), (SELLER, 'different')):
            with self.assertRaises(MeteringConflict):
                MeteringOutbox(self.path, seller, product)
        self.assertEqual(self.box.db.execute('PRAGMA synchronous').fetchone()[0], 2)
        self.assertEqual(self.box.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_database_is_private_and_refuses_public_file_or_symlink(self):
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        public = Path(self.temp.name) / 'public.sqlite'
        public.touch(mode=0o644)
        public.chmod(0o644)
        with self.assertRaises(ValueError):
            MeteringOutbox(str(public), SELLER, PURCHASE.product_code)
        link = Path(self.temp.name) / 'link.sqlite'
        link.symlink_to(self.path)
        with self.assertRaises(OSError):
            MeteringOutbox(str(link), SELLER, PURCHASE.product_code)

    def test_claim_limit_and_concurrent_workers(self):
        for number in range(30):
            self.enqueue(dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + str(number)))
        def claim():
            box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
            try:
                return box.claim(NOW).rows
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            batches = list(pool.map(lambda _: claim(), range(2)))
        self.assertEqual(sorted(map(len, batches)), [5, 25])
        self.assertFalse(set(batches[0]) & set(batches[1]))
        self.assertEqual(self.box.claim(NOW).rows, ())

    def test_concurrent_enqueue_is_one_frozen_record(self):
        def enqueue(quantity):
            box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
            try:
                return box.enqueue(PURCHASE, 'storage_gib_hour', START, quantity, NOW)
            except MeteringConflict:
                return 'conflict'
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(enqueue, [1, 2]))
        self.assertEqual(results.count('conflict'), 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 1)

    def test_lease_expiry_retries_identical_payload_stale_worker_cannot_finish(self):
        key = self.enqueue()
        first = self.box.claim(NOW, lease_seconds=10)
        self.assertFalse(self.box.claim(NOW + timedelta(seconds=9)).rows)
        second = self.box.claim(NOW + timedelta(seconds=10))
        self.assertEqual(first.records, second.records)
        self.assertFalse(self.box.finish(first, {'Results': [self.result(first)]}, NOW + timedelta(seconds=11)))
        self.assertTrue(self.box.finish(second, {'Results': [self.result(second)]}, NOW + timedelta(seconds=11)))
        self.assertFalse(self.box.failed(first, 'late-error', True, NOW + timedelta(seconds=12)))
        self.assertEqual(self.box.inspect(key)['state'], 'accepted')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0], 2)

    def test_process_crash_after_claim_preserves_payload(self):
        key = self.enqueue(quantity=12345)
        # An actual process exits without close/checkpoint/destructors after claim commit.
        code = """import os
from datetime import datetime, timezone
from marketplace_metering import MeteringOutbox
b=MeteringOutbox(os.environ['TEST_DB'], '999999999999', 'test-product')
b.claim(datetime(2026,10,26,2,tzinfo=timezone.utc), lease_seconds=1)
os._exit(0)
"""
        env = dict(os.environ, TEST_DB=self.path, PYTHONPATH=str(Path(__file__).parent.resolve()))
        subprocess.run([sys.executable, '-c', code], env=env, check=True)
        self.box.close()
        self.box = MeteringOutbox(self.path, SELLER, PURCHASE.product_code)
        batch = self.box.claim(NOW + timedelta(seconds=2))
        self.assertEqual(batch.rows, (key,))
        self.assertEqual(batch.records[0]['Quantity'], 12345)
        self.assertEqual(batch.records[0]['LicenseArn'], PURCHASE.license_arn)

    def test_partial_success_unprocessed_and_missing_are_independent(self):
        keys = [self.enqueue(dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + str(i))) for i in range(3)]
        batch = self.box.claim(NOW)
        response = {'Results': [self.result(batch)], 'UnprocessedRecords': [batch.records[1]]}
        self.assertTrue(self.box.finish(batch, response, NOW))
        self.assertEqual([self.box.inspect(key)['state'] for key in keys], ['accepted', 'pending', 'pending'])
        retry = self.box.claim(NOW)
        self.assertEqual(retry.records, batch.records[1:])
        self.assertEqual(self.box.inspect(keys[0])['record_id'], 'record-test')

    def test_duplicate_is_quarantined_not_billed(self):
        for status in ('DuplicateRecord', 'CustomerNotSubscribed'):
            with self.subTest(status=status):
                purchase = dataclasses.replace(PURCHASE, license_arn=PURCHASE.license_arn + status)
                key = self.enqueue(purchase)
                batch = self.box.claim(NOW)
                self.box.finish(batch, {'Results': [self.result(batch, status=status)]}, NOW)
                row = self.box.inspect(key)
                self.assertEqual(row['state'], 'quarantined')
                self.assertIsNone(row['record_id'])
                self.assertEqual(row['reason'], status)
                self.assertFalse(self.box.claim(NOW).rows)

    def test_bad_response_rolls_back_all_outcomes(self):
        key = self.enqueue()
        batch = self.box.claim(NOW)
        valid = self.result(batch)
        changed = dict(batch.records[0], Quantity=2)
        foreign = dict(batch.records[0], LicenseArn=PURCHASE.license_arn + 'other')
        for response in (
            {'Results': [valid, valid]},
            {'Results': [dict(valid, UsageRecord=changed)]},
            {'Results': [dict(valid, UsageRecord=foreign)]},
            {'Results': [dict(valid, Status='Unknown')]},
            {'Results': [dict(valid, MeteringRecordId='')]},
            {'Results': [valid], 'UnprocessedRecords': [batch.records[0]]},
            {'UnprocessedRecords': [changed]},
        ):
            with self.subTest(response=response), self.assertRaises(MeteringProtocolError):
                self.box.finish(batch, response, NOW)
            self.assertEqual(self.box.inspect(key)['state'], 'sending')
            self.assertIsNone(self.box.inspect(key)['record_id'])

    def test_expiry_and_exact_24_hour_boundary(self):
        key = self.enqueue()
        self.assertTrue(self.box.claim(START + timedelta(hours=24, seconds=-1)).rows)
        self.assertFalse(self.box.claim(START + timedelta(hours=24)).rows)
        self.assertEqual(self.box.inspect(key)['reason'], 'deadline_expired')
        with self.assertRaises(ValueError):
            self.enqueue(now=START + timedelta(hours=24))

    def test_previous_month_cutoff_before_normal_24_hours(self):
        start = datetime(2026, 10, 31, 23, tzinfo=UTC)
        key = self.enqueue(timestamp=start, now=start + timedelta(hours=1))
        self.assertTrue(self.box.claim(datetime(2026, 11, 1, 5, 59, 59, tzinfo=UTC)).rows)
        self.assertFalse(self.box.claim(datetime(2026, 11, 1, 6, tzinfo=UTC)).rows)
        self.assertEqual(self.box.inspect(key)['state'], 'quarantined')

    def test_final_deadline_shortens_and_cannot_extend(self):
        end = NOW + timedelta(minutes=5)
        key = self.enqueue(final_deadline=end)
        self.enqueue(final_deadline=NOW + timedelta(hours=1))
        self.assertEqual(self.box.inspect(key)['deadline'], int(end.timestamp()))
        batch = self.box.claim(NOW)
        self.box.shorten_deadline(PURCHASE.license_arn, NOW)
        self.assertFalse(self.box.ready(batch, NOW))
        self.assertFalse(self.box.finish(batch, {'Results': [self.result(batch)]}, NOW))
        self.assertFalse(self.box.claim(NOW).rows)
        self.assertEqual(self.box.inspect(key)['reason'], 'deadline_expired')

    def test_real_sdk_payload_contains_only_concurrent_agreement_identifiers(self):
        key = self.enqueue()
        client = self.sdk()
        expected = {'UsageRecords': [{
            'Timestamp': START, 'CustomerAWSAccountId': PURCHASE.account_id,
            'LicenseArn': PURCHASE.license_arn, 'Dimension': 'storage_gib_hour', 'Quantity': 1,
        }]}
        result = {'Results': [{'UsageRecord': expected['UsageRecords'][0], 'Status': 'Success', 'MeteringRecordId': 'aws-id'}]}
        with Stubber(client) as stub:
            stub.add_response('batch_meter_usage', result, expected)
            self.assertEqual(self.worker(client).dispatch(lambda: NOW), 1)
            stub.assert_no_pending_responses()
        self.assertEqual(self.box.inspect(key)['state'], 'accepted')

    def test_retryable_sdk_failure_retries_exact_record(self):
        key = self.enqueue()
        client = self.sdk()
        record = {'Timestamp': START, 'CustomerAWSAccountId': PURCHASE.account_id,
                  'LicenseArn': PURCHASE.license_arn, 'Dimension': 'storage_gib_hour', 'Quantity': 1}
        with Stubber(client) as stub:
            stub.add_client_error('batch_meter_usage', service_error_code='ThrottlingException', expected_params={'UsageRecords': [record]})
            stub.add_response('batch_meter_usage', {'UnprocessedRecords': [record]}, {'UsageRecords': [record]})
            worker = self.worker(client)
            self.assertEqual(worker.dispatch(lambda: NOW), 0)
            self.assertEqual(self.box.inspect(key)['state'], 'pending')
            worker.dispatch(lambda: NOW)
            stub.assert_no_pending_responses()
        self.assertEqual(self.box.inspect(key)['reason'], 'Unprocessed')

    def test_permanent_sdk_error_quarantines(self):
        key = self.enqueue()
        client = self.sdk()
        with Stubber(client) as stub:
            stub.add_client_error('batch_meter_usage', service_error_code='InvalidLicenseException')
            self.worker(client).dispatch(lambda: NOW)
        self.assertEqual(self.box.inspect(key)['state'], 'quarantined')
        self.assertEqual(self.box.inspect(key)['reason'], 'InvalidLicenseException')

    def test_transport_error_preserves_record(self):
        key = self.enqueue()
        client = Mock()
        client.batch_meter_usage.side_effect = EndpointConnectionError(endpoint_url='https://example.invalid')
        self.worker(client).dispatch(lambda: NOW)
        self.assertEqual(self.box.inspect(key)['state'], 'pending')
        self.assertEqual(self.box.claim(NOW).records[0]['Quantity'], 1)

    def test_wrong_seller_and_empty_queue_never_meter(self):
        client, sts = Mock(), Mock()
        sts.get_caller_identity.return_value = {'Account': '111111111111'}
        with self.assertRaises(MarketplaceDenied):
            MeteringWorker(self.box, sts, client)
        client.batch_meter_usage.assert_not_called()
        self.assertEqual(self.worker(client).dispatch(lambda: NOW), 0)
        client.batch_meter_usage.assert_not_called()

    def test_deadline_rechecked_immediately_before_sdk(self):
        self.enqueue(final_deadline=NOW + timedelta(seconds=1))
        times = iter((NOW, NOW + timedelta(seconds=1)))
        client = Mock()
        self.assertEqual(self.worker(client).dispatch(lambda: next(times)), 0)
        client.batch_meter_usage.assert_not_called()

    def test_late_success_retained_for_reconciliation_without_state_regression(self):
        key = self.enqueue(final_deadline=NOW + timedelta(seconds=1))
        batch = self.box.claim(NOW)
        late = NOW + timedelta(seconds=2)
        self.assertFalse(self.box.finish(batch, {'Results': [self.result(batch)]}, late))
        self.assertFalse(self.box.claim(late).rows)
        self.assertEqual(self.box.inspect(key)['state'], 'quarantined')
        audit = self.box.db.execute('SELECT outcomes FROM responses').fetchone()[0]
        self.assertIn('record-test', audit)
        self.assertIn('accepted', audit)

    def test_remote_acceptance_then_local_commit_failure_retries_same_payload(self):
        key = self.enqueue()
        self.box.db.execute("""CREATE TRIGGER fail_accept BEFORE UPDATE OF state ON usage
            WHEN NEW.state='accepted' BEGIN SELECT RAISE(ABORT, 'disk-fault'); END""")
        client = self.sdk()
        record = {'Timestamp': START, 'CustomerAWSAccountId': PURCHASE.account_id,
                  'LicenseArn': PURCHASE.license_arn, 'Dimension': 'storage_gib_hour', 'Quantity': 1}
        response = {'Results': [{'UsageRecord': record, 'Status': 'Success', 'MeteringRecordId': 'same-record-id'}]}
        with Stubber(client) as stub:
            stub.add_response('batch_meter_usage', response, {'UsageRecords': [record]})
            stub.add_response('batch_meter_usage', response, {'UsageRecords': [record]})
            worker = self.worker(client)
            with self.assertRaises(sqlite3.IntegrityError):
                worker.dispatch(lambda: NOW)
            self.assertEqual(self.box.inspect(key)['state'], 'sending')
            self.box.db.execute('DROP TRIGGER fail_accept')
            worker.dispatch(lambda: NOW + timedelta(seconds=121))
            stub.assert_no_pending_responses()
        self.assertEqual(self.box.inspect(key)['state'], 'accepted')
        self.assertEqual(self.box.inspect(key)['record_id'], 'same-record-id')
        self.assertEqual(self.enqueue(), key)
        self.assertFalse(self.box.claim(NOW + timedelta(seconds=121)).rows)

    def test_rollback_on_fault_does_not_lose_pending_usage(self):
        key = self.enqueue()
        self.box.db.execute("""CREATE TRIGGER injected_claim_failure BEFORE INSERT ON attempts
                             BEGIN SELECT RAISE(ABORT, 'injected'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.box.claim(NOW)
        self.assertEqual(self.box.inspect(key)['state'], 'pending')
        self.assertIsNone(self.box.inspect(key)['lease'])
        self.box.db.execute('DROP TRIGGER injected_claim_failure')
        self.assertEqual(self.box.claim(NOW).rows, (key,))


if __name__ == '__main__':
    unittest.main()
