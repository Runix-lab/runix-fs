"""Exact accounting, replay, transaction and crash recovery tests; no AWS calls."""
import dataclasses
import json
import os
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from fractions import Fraction
from unittest.mock import Mock

import boto3
from botocore.stub import Stubber

from marketplace_adapter import MarketplaceDenied, Purchase
from marketplace_metering import MeteringConflict, MeteringOutbox, MeteringWorker
from marketplace_storage_usage import BYTE_SECONDS_PER_UNIT, DIMENSION, StorageUsageLedger

UTC = timezone.utc
START = datetime(2026, 10, 27, 1, tzinfo=UTC)
GIB = 1 << 30
SELLER = '999999999999'
BUYER = Purchase('123456789012', 'arn:aws:license-manager:us-east-1:999999999999:license:synthetic', 'test-product', 'agreement-test')


class StorageUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'usage.sqlite')
        self.box = MeteringOutbox(self.path, SELLER, BUYER.product_code)
        self.ledger = StorageUsageLedger(self.box)

    def tearDown(self):
        self.box.close()
        self.temp.cleanup()

    def activate(self, start=START, buyer=BUYER):
        return self.ledger.activate(buyer, start, start)

    def append(self, source, left, right, size, buyer=BUYER):
        return self.ledger.append(buyer, source, left, right, size, right)

    def records(self):
        return [json.loads(row[0]) for row in self.box.db.execute('SELECT payload FROM usage ORDER BY hour')]

    def test_no_accounting_before_activation(self):
        with self.assertRaises(MeteringConflict):
            self.append('event', START, START + timedelta(seconds=1), GIB)
        with self.assertRaises(MeteringConflict):
            self.ledger.seal(BUYER, START, START)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM licenses').fetchone()[0], 0)
        self.assertFalse(self.records())

    def test_exact_carry_across_hours_and_subsample_splitting(self):
        self.activate()
        now = START
        for number in range(120):
            end = now + timedelta(seconds=60)
            self.append('minute-' + str(number), now, end, GIB // 2)
            now = end
            if number in (59, 119):
                state = self.ledger.seal(BUYER, now, now)
                self.assertEqual(int(state['remainder']), BYTE_SECONDS_PER_UNIT // 2 if number == 59 else 0)
        self.assertEqual([r['Quantity'] for r in self.records()], [0, 1])
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM storage_intervals').fetchone()[0], 120)

    def test_final_partial_hour_waives_only_fraction_and_stops_future_usage(self):
        self.activate()
        end = START + timedelta(minutes=45)
        self.append('usage', START, end, 2 * GIB)
        deadline = end + timedelta(hours=1)
        state = self.ledger.seal(BUYER, end, end, final=True, final_deadline=deadline)
        self.assertEqual([r['Quantity'] for r in self.records()], [1])
        self.assertEqual(int(state['waived']), BYTE_SECONDS_PER_UNIT // 2)
        self.assertEqual(int(state['remainder']), 0)
        self.assertTrue(state['closed'])
        self.assertEqual(state, self.ledger.seal(BUYER, end, end, final=True, final_deadline=deadline))
        with self.assertRaises(MeteringConflict):
            self.append('late', end, end + timedelta(seconds=1), GIB)
        self.assertFalse(self.append('usage', START, end, 2 * GIB))
        self.assertEqual(self.ledger.activate(BUYER, START, end)['closed'], 1)
        with self.assertRaises(MeteringConflict):
            self.ledger.activate(BUYER, end, end)

    def test_final_at_already_sealed_hour_waives_carried_fraction_once(self):
        self.activate()
        end = START + timedelta(hours=1)
        self.append('usage', START, end, GIB // 2)
        self.ledger.seal(BUYER, end, end)
        result = self.ledger.seal(BUYER, end, end, final=True)
        self.assertEqual(int(result['waived']), BYTE_SECONDS_PER_UNIT // 2)
        self.assertEqual(self.ledger.seal(BUYER, end, end, final=True), result)
        self.assertEqual(len(self.records()), 1)

    def test_mid_hour_start_is_not_backdated_and_cross_hour_interval_splits(self):
        start = START + timedelta(minutes=30)
        self.activate(start)
        end = start + timedelta(hours=1)
        self.append('cross-hour', start, end, 2 * GIB)
        self.ledger.seal(BUYER, START + timedelta(hours=1), end)
        self.ledger.seal(BUYER, end, end, final=True)
        rows = self.records()
        self.assertEqual([r['Quantity'] for r in rows], [1, 1])
        self.assertEqual(rows[0]['Timestamp'], int(start.timestamp()))
        self.assertEqual(rows[1]['Timestamp'], int((START + timedelta(hours=1)).timestamp()))

    def test_zero_usage_still_produces_hourly_zero(self):
        self.activate()
        end = START + timedelta(hours=1)
        self.append('empty', START, end, 0)
        self.ledger.seal(BUYER, end, end)
        self.assertEqual(self.records()[0]['Quantity'], 0)

    def test_source_replay_conflict_order_and_gap(self):
        self.activate()
        end = START + timedelta(minutes=1)
        self.assertTrue(self.append('one', START, end, GIB))
        self.assertFalse(self.append('one', START, end, GIB))
        for event, left, right, size in (
            ('one', START, end, 2 * GIB),
            ('overlap', START, end, GIB),
            ('gap', end + timedelta(seconds=1), end + timedelta(seconds=2), GIB),
            ('one', end, end + timedelta(seconds=1), GIB),
        ):
            with self.subTest(event=event), self.assertRaises(MeteringConflict):
                self.append(event, left, right, size)
        self.assertEqual(self.ledger.status(BUYER)['observed'], int(end.timestamp()))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM storage_intervals').fetchone()[0], 1)

    def test_strict_parameter_and_unobserved_seal_validation(self):
        self.activate()
        end = START + timedelta(seconds=1)
        for size in (-1, True, 1.2, str(GIB), 1 << 63):
            with self.assertRaises(ValueError):
                self.append('bad', START, end, size)
        for left, right in ((START, START), (end, START), (START, START + timedelta(seconds=3601)),
                            (START.replace(tzinfo=None), end), (START, end.replace(microsecond=1))):
            with self.assertRaises(ValueError):
                self.append('bad', left, right, 1)
        with self.assertRaises(ValueError):
            self.ledger.append(BUYER, 'future', START, end, GIB, START)
        with self.assertRaises(ValueError):
            self.ledger.append(BUYER, 'bad event', START, end, GIB, end)
        with self.assertRaises(ValueError):
            self.ledger.seal(BUYER, end, end)
        with self.assertRaises(MeteringConflict):
            self.ledger.seal(BUYER, START + timedelta(hours=1), START + timedelta(hours=1))
        self.assertFalse(self.records())

    def test_cross_buyer_binding_and_two_concurrent_licenses(self):
        self.activate()
        changed = dataclasses.replace(BUYER, account_id='888888888888')
        with self.assertRaises(MeteringConflict):
            self.ledger.activate(changed, START, START)
        with self.assertRaises(MarketplaceDenied):
            self.ledger.activate(dataclasses.replace(BUYER, product_code='wrong'), START, START)
        other = dataclasses.replace(BUYER, license_arn=BUYER.license_arn + '2', agreement_id='agreement-2')
        self.activate(buyer=other)
        end = START + timedelta(hours=1)
        for buyer, size in ((BUYER, GIB // 2), (other, GIB)):
            self.append('same-event-id', START, end, size, buyer)
            self.ledger.seal(buyer, end, end)
        self.assertEqual(sorted(r['Quantity'] for r in self.records()), [0, 1])
        self.assertEqual(int(self.ledger.status(BUYER)['remainder']), BYTE_SECONDS_PER_UNIT // 2)
        self.assertEqual(int(self.ledger.status(other)['remainder']), 0)

    def test_manual_record_cannot_be_mixed_with_stream_activation(self):
        self.box.enqueue(BUYER, DIMENSION, START, 3, START)
        with self.assertRaises(MeteringConflict):
            self.activate()

    def test_large_byte_seconds_are_text_not_overflowed_sqlite_integer(self):
        self.activate()
        end = START + timedelta(hours=1)
        self.append('very-large', START, end, (1 << 63) - 1)
        total = self.box.db.execute('SELECT byte_seconds FROM storage_hours').fetchone()[0]
        self.assertEqual(int(total), ((1 << 63) - 1) * 3600)
        with self.assertRaises(ValueError):
            self.ledger.seal(BUYER, end, end)
        self.assertFalse(self.records())
        self.assertEqual(self.ledger.status(BUYER)['sealed'], int(START.timestamp()))

    def test_sealing_partial_failure_rolls_back_first_enqueue_and_remainder(self):
        self.activate()
        one, two = START + timedelta(hours=1), START + timedelta(hours=2)
        self.append('one', START, one, GIB // 2)
        self.append('two', one, two, GIB // 2)
        hour = int(one.timestamp()) // 3600
        self.box.db.execute(f'''CREATE TRIGGER fail_second BEFORE INSERT ON usage
            WHEN NEW.hour={hour} BEGIN SELECT RAISE(ABORT, 'injected'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.ledger.seal(BUYER, two, two)
        self.assertFalse(self.records())
        self.assertEqual(self.ledger.status(BUYER)['remainder'], '0')
        self.assertEqual(self.ledger.status(BUYER)['sealed'], int(START.timestamp()))
        self.box.db.execute('DROP TRIGGER fail_second')
        self.ledger.seal(BUYER, two, two)
        self.assertEqual([r['Quantity'] for r in self.records()], [0, 1])

    def test_append_transaction_failure_rolls_back_event_and_buckets(self):
        self.activate()
        self.box.db.execute('''CREATE TRIGGER fail_observed BEFORE UPDATE OF observed ON storage_streams
            BEGIN SELECT RAISE(ABORT, 'injected'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.append('event', START, START + timedelta(seconds=1), GIB)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM storage_intervals').fetchone()[0], 0)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM storage_hours').fetchone()[0], 0)

    def test_concurrent_append_and_seal_consume_usage_once(self):
        self.activate()
        end = START + timedelta(hours=1)
        def append_or_seal(mode):
            box = MeteringOutbox(self.path, SELLER, BUYER.product_code)
            ledger = StorageUsageLedger(box)
            try:
                if mode == 'append':
                    return ledger.append(BUYER, 'same-event', START, end, GIB // 2, end)
                return ledger.seal(BUYER, end, end)
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(append_or_seal, ['append', 'append']))
        self.assertEqual(sorted(results), [False, True])
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(append_or_seal, ['seal', 'seal']))
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(int(self.ledger.status(BUYER)['remainder']), BYTE_SECONDS_PER_UNIT // 2)

    def test_month_boundary_and_time_zone(self):
        start = datetime(2026, 10, 31, 23, 30, tzinfo=UTC)
        self.activate(start)
        end = start + timedelta(hours=1)
        self.append('month-rollover', start.astimezone(timezone(timedelta(hours=8))), end, GIB)
        self.ledger.seal(BUYER, end, end, final=True)
        rows = self.box.db.execute('SELECT hour,deadline FROM usage ORDER BY hour').fetchall()
        self.assertEqual(rows[0]['deadline'], int(datetime(2026, 11, 1, 6, tzinfo=UTC).timestamp()))
        self.assertEqual([r['Quantity'] for r in self.records()], [0, 1])

    def test_process_exit_after_seal_preserves_carry_and_outbox(self):
        self.activate()
        one, two = START + timedelta(hours=1), START + timedelta(hours=2)
        self.append('first', START, one, GIB // 2)
        code = '''import os
from datetime import datetime, timezone
from marketplace_metering import MeteringOutbox
from marketplace_storage_usage import StorageUsageLedger
from marketplace_adapter import Purchase
b=MeteringOutbox(os.environ['TEST_DB'], '999999999999', 'test-product')
p=Purchase('123456789012','arn:aws:license-manager:us-east-1:999999999999:license:synthetic','test-product','agreement-test')
t=datetime(2026,10,27,2,tzinfo=timezone.utc)
StorageUsageLedger(b).seal(p,t,t)
os._exit(0)
'''
        subprocess.run([sys.executable, '-c', code], check=True,
                       env=dict(os.environ, TEST_DB=self.path, PYTHONPATH=str(Path(__file__).parent.resolve())))
        self.box.close()
        self.box = MeteringOutbox(self.path, SELLER, BUYER.product_code)
        self.ledger = StorageUsageLedger(self.box)
        self.append('second', one, two, GIB // 2)
        self.ledger.seal(BUYER, two, two)
        self.assertEqual([r['Quantity'] for r in self.records()], [0, 1])

    def test_real_sdk_request_from_interval_to_worker(self):
        self.activate()
        end = START + timedelta(hours=1)
        self.append('engine-interval-fixture', START, end, 2 * GIB)
        self.ledger.seal(BUYER, end, end)
        client = boto3.client('meteringmarketplace', region_name='us-east-1', aws_access_key_id='test-only', aws_secret_access_key='test-only')
        record = dict(Timestamp=START, CustomerAWSAccountId=BUYER.account_id,
                      LicenseArn=BUYER.license_arn, Dimension=DIMENSION, Quantity=2)
        sts = Mock()
        sts.get_caller_identity.return_value = {'Account': SELLER}
        with Stubber(client) as stub:
            stub.add_response('batch_meter_usage', {'Results': [dict(UsageRecord=record, Status='Success', MeteringRecordId='test-record')]}, {'UsageRecords': [record]})
            MeteringWorker(self.box, sts, client).dispatch(lambda: end)
            stub.assert_no_pending_responses()
        self.assertEqual(self.box.db.execute('SELECT state FROM usage').fetchone()[0], 'accepted')

    def test_variable_usage_matches_independent_fraction_reference(self):
        self.activate()
        generator = random.Random(20261027)
        current = START
        boundary = START + timedelta(hours=1)
        exact = Fraction(0)
        for number in range(180):
            seconds = generator.randint(1, 120)
            size = generator.randint(0, 3 * GIB)
            end = current + timedelta(seconds=seconds)
            self.append('variable-' + str(number), current, end, size)
            exact += Fraction(size * seconds, BYTE_SECONDS_PER_UNIT)
            while boundary <= end:
                self.ledger.seal(BUYER, boundary, end)
                boundary += timedelta(hours=1)
            current = end
        state = self.ledger.seal(BUYER, current, current, final=True)
        charged = sum(row['Quantity'] for row in self.records())
        self.assertEqual(charged, exact.numerator // exact.denominator)
        self.assertEqual(Fraction(int(state['waived']), BYTE_SECONDS_PER_UNIT), exact - charged)

    def test_byte_count_above_float_precision_stays_exact(self):
        self.activate()
        end = START + timedelta(hours=1)
        size = (1 << 53) + 1
        self.append('precision-boundary', START, end, size)
        state = self.ledger.seal(BUYER, end, end)
        self.assertEqual(self.records()[0]['Quantity'], 1 << 23)
        self.assertEqual(int(state['remainder']), 3600)


if __name__ == '__main__':
    unittest.main()
