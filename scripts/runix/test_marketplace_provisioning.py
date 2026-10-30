"""Real SQLite/auth-binding/license reducers; synthetic agreements, no provider."""
import contextlib
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase, RegistrationGateway
from marketplace_agreement import AgreementSnapshot
from marketplace_lifecycle import DEPROVISIONED
from marketplace_metering import MeteringConflict, MeteringOutbox
from marketplace_payg_license import PaygLicenseState
from marketplace_provisioning import LocalProfile, ProvisioningBusy, ProvisioningJournal
from marketplace_registration import RegistrationRegistry
from test_marketplace_payg_license import SELLER, PRODUCT, PRODUCT_ID, NOW, PURCHASE, ISSUER, PRINCIPAL, event

PROFILE = LocalProfile('local-acceptance', 'sha256:' + 'a' * 64, 'b' * 40)


class Reader:
    seller_account, product_code, product_id = SELLER, PRODUCT, PRODUCT_ID
    def __init__(self):
        self.hook = None
        self.status, self.ends = 'ACTIVE', None
    def describe(self, purchase, now):
        if self.hook:
            self.hook(purchase, now)
        return AgreementSnapshot(purchase.agreement_id, self.status, NOW - timedelta(days=1), self.ends, now)


def fixture(path):
    box = MeteringOutbox(str(path), SELLER, PRODUCT)
    sts, meter, reader = Mock(), Mock(), Reader()
    sts.get_caller_identity.return_value = {'Account': SELLER}
    registry = RegistrationRegistry(box, RegistrationGateway(sts, meter, SELLER, PRODUCT), ISSUER)
    licenses = PaygLicenseState(box, PRODUCT_ID, reader)
    return box, registry, licenses, meter, reader


def bind(registry, licenses, meter, purchase=PURCHASE, org='org-one'):
    licenses.record_update(event(purchase), NOW)
    registry.set_membership(org, PRINCIPAL.subject, 'owner')
    meter.resolve_customer.return_value = {'CustomerAWSAccountId': purchase.account_id,
        'ProductCode': PRODUCT, 'LicenseArn': purchase.license_arn, 'Metadata': {'AgreementId': purchase.agreement_id}}
    claim = registry.register('synthetic-registration-token', NOW)
    return registry.bind(PRINCIPAL, org, claim, NOW)['id']


class ProvisioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'work.sqlite'
        self.box, self.registry, self.licenses, self.meter, self.reader = fixture(self.path)
        self.addCleanup(self.box.close)
        self.journal = ProvisioningJournal(self.licenses, PROFILE, 2)
        self.intent = bind(self.registry, self.licenses, self.meter)

    def reserve(self, intent=None, at=NOW):
        return self.journal.reserve(intent or self.intent, clock=lambda: at)

    def leased(self, at=NOW, **kwargs):
        work = self.reserve()
        return self.journal.claim(work.operation_key, 'worker-one', clock=lambda: at, **kwargs)

    def audit_failure(self):
        self.box.db.execute("""CREATE TEMP TRIGGER work_audit_failure BEFORE INSERT ON provisioning_work_events
            BEGIN SELECT RAISE(ABORT,'synthetic audit failure'); END""")

    def drop_audit_failure(self):
        self.box.db.execute('DROP TRIGGER work_audit_failure')

    def stop(self, at=NOW):
        self.licenses.negative.apply(event(kind=DEPROVISIONED, at=at), at)

    def test_reservation_replay_preserves_key_slot_and_pending_registration(self):
        work = self.reserve()
        self.assertEqual(work, self.reserve())
        self.assertEqual(work.state, 'reserved')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work_events').fetchone()[0], 1)
        self.assertEqual(self.box.db.execute('SELECT state FROM provisioning_intents').fetchone()[0], 'pending_license_verification')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM usage').fetchone()[0], 0)
        self.assertFalse(hasattr(self.journal, 'activate'))
        self.assertFalse(hasattr(self.journal, 'delete_data'))

    def test_profile_and_limit_cannot_change_silently(self):
        for profile, count in ((replace(PROFILE, source_commit='c' * 40), 2), (PROFILE, 3)):
            with self.assertRaises(MeteringConflict):
                ProvisioningJournal(self.licenses, profile, count)
        self.reserve()

    def test_invalid_profiles_limits_and_identifiers(self):
        for profile, count in ((PROFILE, True), (PROFILE, 0), (PROFILE, 257),
                (replace(PROFILE, image_id='image:latest'), 2), (replace(PROFILE, source_commit='main'), 2)):
            with self.assertRaises(ValueError):
                ProvisioningJournal(self.licenses, profile, count)
        for intent in ('bad', None, '../intent'):
            with self.assertRaises(MarketplaceDenied):
                self.journal.reserve(intent, clock=lambda: NOW)
        work = self.reserve()
        for value in (0, 31, True, 0.5):
            with self.assertRaises(ValueError):
                self.journal.claim(work.operation_key, 'worker', lease_seconds=value, clock=lambda: NOW)
        with self.assertRaises(ValueError):
            self.journal.claim(work.operation_key, '../worker', clock=lambda: NOW)
        with self.assertRaises(ValueError):
            self.journal.inspect('../work')

    def test_missing_inactive_or_unconfigured_license_never_reserves(self):
        for status in ('CANCELLED', 'EXPIRED'):
            self.reader.status = status
            with self.assertRaises(MarketplaceDenied):
                self.reserve()
        self.reader.status = 'ACTIVE'
        self.licenses.reader = None
        with self.assertRaises(MarketplaceUnavailable):
            self.reserve()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 0)

    def test_unauthorized_binding_does_not_create_work(self):
        with self.assertRaises(MarketplaceDenied):
            self.registry.bind(replace(PRINCIPAL, subject='foreign-user'), 'org-one', 'x' * 43, NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 0)

    def test_unknown_intent_or_missing_trusted_update_never_reserves(self):
        with self.assertRaises(MarketplaceDenied):
            self.journal.reserve('0' * 32, clock=lambda: NOW)
        self.box.db.execute('DELETE FROM payg_license_updates')
        self.reader.hook = lambda p,n: self.fail('unverified license must not reach AWS reader')
        with self.assertRaises(MarketplaceDenied):
            self.reserve()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 0)

    def test_transaction_wait_can_expire_observation_before_reservation(self):
        real = self.box.transaction
        now, count = [NOW], [0]
        @contextlib.contextmanager
        def delayed():
            with real():
                count[0] += 1
                if count[0] == 3:
                    now[0] = NOW + timedelta(seconds=31)
                yield
        with patch.object(self.box, 'transaction', side_effect=delayed):
            with self.assertRaises(MarketplaceUnavailable):
                self.journal.reserve(self.intent, clock=lambda: now[0])
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 0)

    def test_transaction_wait_never_resurrects_expired_renewal(self):
        lease = self.leased()
        real = self.box.transaction
        now, count = [NOW], [0]
        @contextlib.contextmanager
        def delayed():
            with real():
                count[0] += 1
                if count[0] == 4:
                    now[0] = NOW + timedelta(seconds=31)
                yield
        with patch.object(self.box, 'transaction', side_effect=delayed):
            with self.assertRaises(MarketplaceUnavailable):
                self.journal.renew(lease, clock=lambda: now[0])
        self.assertEqual(self.box.db.execute('SELECT lease_until FROM provisioning_work').fetchone()[0], int(lease.valid_until.timestamp()))

    def test_lease_checks_use_clock_after_transaction_lock(self):
        lease = self.leased()
        real = self.box.transaction
        now = [NOW]
        @contextlib.contextmanager
        def delayed():
            with real():
                now[0] = NOW + timedelta(seconds=31)
                yield
        for action in (lambda:self.journal.assert_current(lease, clock=lambda: now[0]),
                       lambda:self.journal.record_failure(lease, 'verification_failed', clock=lambda: now[0])):
            now[0] = NOW
            with patch.object(self.box, 'transaction', side_effect=delayed):
                with self.assertRaises(MarketplaceDenied):
                    action()
        self.assertEqual(self.journal.inspect(lease.operation_key).state, 'leased')

    def test_existing_outer_transaction_cannot_hold_lock_across_aws(self):
        self.reader.hook = lambda p,n: self.fail('must reject before external read')
        with self.box.transaction():
            with self.assertRaises(MarketplaceUnavailable):
                self.reserve()

    def test_live_lease_blocks_duplicate_claim_and_hides_token_in_repr(self):
        lease = self.leased()
        self.assertNotIn(lease.token, repr(lease))
        self.assertEqual(lease.valid_until, NOW + timedelta(seconds=30))
        self.assertEqual(self.journal.assert_current(lease, clock=lambda: NOW).epoch, 1)
        with self.assertRaises(ProvisioningBusy):
            self.journal.claim(lease.operation_key, 'worker-two', clock=lambda: NOW)

    def test_expiry_takeover_increments_epoch_without_allocating_another_slot(self):
        first = self.leased(lease_seconds=5)
        second = self.journal.claim(first.operation_key, 'worker-two', clock=lambda: NOW + timedelta(seconds=5))
        self.assertEqual(second.epoch, first.epoch + 1)
        self.assertNotEqual(second.token, first.token)
        with self.assertRaises(MarketplaceDenied):
            self.journal.assert_current(first, clock=lambda: NOW + timedelta(seconds=5))
        with self.assertRaises(MarketplaceDenied):
            self.journal.record_failure(first, 'provisioning_failed', clock=lambda: NOW + timedelta(seconds=5))
        self.assertEqual(self.reserve(at=NOW + timedelta(seconds=5)).operation_key, first.operation_key)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 1)

    def test_forged_lease_fields_cannot_mutate_work(self):
        lease = self.leased()
        for changed in (replace(lease, token='f' * 32), replace(lease, epoch=lease.epoch+1), replace(lease, worker='foreign')):
            with self.assertRaises(MarketplaceDenied):
                self.journal.record_failure(changed, 'verification_failed', clock=lambda: NOW)
        with self.assertRaises(ValueError):
            self.journal.record_failure(lease, 'raw AWS secret/error body', clock=lambda: NOW)
        self.assertEqual(self.journal.inspect(lease.operation_key).state, 'leased')

    def test_renewal_rechecks_and_never_extends_past_agreement_end(self):
        lease = self.leased()
        self.reader.ends = NOW + timedelta(seconds=20)
        renewed = self.journal.renew(lease, clock=lambda: NOW + timedelta(seconds=5))
        self.assertEqual(renewed.valid_until, self.reader.ends)
        self.assertEqual((renewed.token, renewed.epoch), (lease.token, lease.epoch))
        with self.assertRaises(MarketplaceDenied):
            self.journal.assert_current(renewed, clock=lambda: self.reader.ends)

    def test_renewal_does_not_resurrect_expired_lease(self):
        lease = self.leased(lease_seconds=1)
        with self.assertRaises(MarketplaceDenied):
            self.journal.renew(lease, clock=lambda: NOW + timedelta(seconds=1))

    def test_idempotent_renewal_does_not_duplicate_audit(self):
        lease = self.leased()
        self.journal.renew(lease, clock=lambda: NOW)
        self.journal.renew(lease, clock=lambda: NOW)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work_events').fetchone()[0], 2)

    def test_failure_requeues_same_operation_but_retains_capacity(self):
        lease = self.leased()
        self.journal.record_failure(lease, 'provider_unavailable', clock=lambda: NOW)
        self.assertEqual(self.journal.inspect(lease.operation_key).state, 'reserved')
        retry = self.journal.claim(lease.operation_key, 'worker-two', clock=lambda: NOW)
        self.assertEqual(retry.epoch, lease.epoch+1)
        self.assertEqual(self.reserve().operation_key, lease.operation_key)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 1)

    def test_stop_immediately_fences_lease_before_reducer_and_preserves_slot(self):
        lease = self.leased()
        self.stop()
        with self.assertRaises(MarketplaceDenied):
            self.journal.assert_current(lease, clock=lambda: NOW)
        self.assertEqual(self.journal.reconcile_stops(NOW), 1)
        self.assertEqual(self.journal.reconcile_stops(NOW), 0)
        self.assertEqual(self.journal.inspect(lease.operation_key).state, 'stop_requested')
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 1)
        with self.assertRaises(MarketplaceDenied):
            self.reserve()

    def test_clock_rollback_cannot_delay_negative_fence(self):
        lease = self.leased(at=NOW + timedelta(seconds=10))
        self.stop(at=NOW + timedelta(seconds=11))
        self.assertEqual(self.journal.reconcile_stops(NOW), 1)
        self.assertEqual(self.journal.inspect(lease.operation_key).epoch, lease.epoch+1)

    def test_changed_org_binding_is_never_reinterpreted(self):
        lease = self.leased()
        with self.box.transaction():
            self.box.db.execute("UPDATE org_purchases SET org='foreign'")
            self.box.db.execute("UPDATE provisioning_intents SET org='foreign'")
        with self.assertRaises(MeteringConflict):
            self.journal.assert_current(lease, clock=lambda: NOW)
        with self.assertRaises(MeteringConflict):
            self.reserve()

    def test_clock_rollback_blocks_positive_updates(self):
        lease = self.leased(at=NOW + timedelta(seconds=10))
        for action in (lambda:self.reserve(at=NOW), lambda:self.journal.renew(lease, clock=lambda: NOW),
                       lambda:self.journal.record_failure(lease, 'verification_failed', clock=lambda: NOW)):
            with self.assertRaises(MarketplaceUnavailable):
                action()

    def test_cancellation_during_external_read_commits_without_write_lock(self):
        def stop_during_read(purchase, now):
            other, _, state, _, _ = fixture(self.path)
            try:
                state.negative.apply(event(kind=DEPROVISIONED, at=now), now)
            finally:
                other.close()
        self.reader.hook = stop_during_read
        with self.assertRaises(MarketplaceDenied):
            self.reserve()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 0)

    def test_takeover_during_renewal_cannot_be_overwritten_by_old_worker(self):
        lease = self.leased()
        current = [NOW + timedelta(seconds=5)]
        def takeover(purchase, now):
            other, _, state, _, _ = fixture(self.path)
            try:
                journal = ProvisioningJournal(state, PROFILE, 2)
                journal.claim(lease.operation_key, 'worker-two', clock=lambda: NOW + timedelta(seconds=31))
                current[0] = NOW + timedelta(seconds=31)
            finally:
                other.close()
        self.reader.hook = takeover
        with self.assertRaises(MarketplaceDenied):
            self.journal.renew(lease, clock=lambda: current[0])
        self.assertEqual(self.journal.inspect(lease.operation_key).epoch, lease.epoch+1)

    def test_reservation_and_audit_rollback_together(self):
        self.audit_failure()
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 0)
        self.drop_audit_failure()
        self.reserve()

    def test_claim_and_renewal_audit_failure_do_not_advance_state(self):
        work = self.reserve()
        self.audit_failure()
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.claim(work.operation_key, 'worker-one', clock=lambda: NOW)
        self.assertEqual(self.journal.inspect(work.operation_key).epoch, 0)
        self.drop_audit_failure()
        lease = self.journal.claim(work.operation_key, 'worker-one', clock=lambda: NOW)
        self.audit_failure()
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.renew(lease, clock=lambda: NOW + timedelta(seconds=5))
        self.assertEqual(self.box.db.execute('SELECT lease_until FROM provisioning_work').fetchone()[0], int(lease.valid_until.timestamp()))

    def test_failure_and_stop_audit_rollback_without_releasing_slot(self):
        lease = self.leased()
        self.audit_failure()
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.record_failure(lease, 'provisioning_failed', clock=lambda: NOW)
        self.assertEqual(self.journal.inspect(lease.operation_key).state, 'leased')
        self.stop()
        with self.assertRaises(sqlite3.IntegrityError):
            self.journal.reconcile_stops(NOW)
        self.assertEqual(self.journal.inspect(lease.operation_key).state, 'leased')
        self.drop_audit_failure()
        self.assertEqual(self.journal.reconcile_stops(NOW), 1)

    def concurrent(self, intents, claim=False):
        barrier = threading.Barrier(len(intents))
        def worker(intent):
            box, _, state, _, reader = fixture(self.path)
            try:
                journal = ProvisioningJournal(state, PROFILE, 2)
                reader.hook = lambda p,n: barrier.wait(timeout=5)
                if claim:
                    return journal.claim(intent, 'worker', clock=lambda: NOW)
                return journal.reserve(intent, clock=lambda: NOW)
            except ProvisioningBusy:
                return None
            finally:
                box.close()
        with ThreadPoolExecutor(max_workers=len(intents)) as pool:
            return list(pool.map(worker, intents))

    def test_concurrent_replay_reserves_one_operation(self):
        results = self.concurrent([self.intent, self.intent])
        self.assertEqual(results[0].operation_key, results[1].operation_key)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 1)

    def test_concurrent_claim_has_one_live_owner(self):
        work = self.reserve()
        results = self.concurrent([work.operation_key, work.operation_key], claim=True)
        self.assertEqual(sum(x is not None for x in results), 1)

    def test_concurrent_capacity_reservations_do_not_overbook(self):
        self.reserve()
        intents = []
        for n in (2,3):
            purchase = Purchase(PURCHASE.account_id, PURCHASE.license_arn + str(n), PRODUCT, PURCHASE.agreement_id + str(n))
            intents.append(bind(self.registry, self.licenses, self.meter, purchase, 'org-' + str(n)))
        results = self.concurrent(intents)
        self.assertEqual(sum(x is not None for x in results), 1)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0], 2)

    def test_real_process_exit_after_reservation_and_claim_preserves_identity(self):
        code = '''import os,sys
from test_marketplace_provisioning import fixture,PROFILE,NOW
from marketplace_provisioning import ProvisioningJournal
box,_,licenses,_,_=fixture(sys.argv[1])
journal=ProvisioningJournal(licenses,PROFILE,2)
work=journal.reserve(sys.argv[2],clock=lambda:NOW)
journal.claim(work.operation_key,'crashed-worker',clock=lambda:NOW)
os._exit(0)
'''
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent), AWS_EC2_METADATA_DISABLED='true')
        subprocess.run([sys.executable, '-c', code, str(self.path), self.intent], check=True, env=env, capture_output=True, timeout=20)
        row = self.box.db.execute('SELECT operation,epoch,state FROM provisioning_work').fetchone()
        self.assertEqual((row['epoch'], row['state']), (1, 'leased'))
        lease = self.journal.claim(row['operation'], 'replacement', clock=lambda: NOW + timedelta(seconds=31))
        self.assertEqual(lease.epoch, 2)
        self.assertEqual(self.reserve(at=NOW + timedelta(seconds=31)).operation_key, row['operation'])


if __name__ == '__main__':
    unittest.main()
