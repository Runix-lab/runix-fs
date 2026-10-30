"""Internal durable work reservation and fencing; never a resource grant.

No provider calls, HTTP dispatch, ACTIVE state or customer-data deletion.
"""
import hashlib
import json
import re
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable
from marketplace_metering import MeteringConflict, instant
from marketplace_payg_license import utc_now


class ProvisioningBusy(MarketplaceUnavailable):
    pass


@dataclass(frozen=True)
class LocalProfile:
    name: str
    image_id: str
    source_commit: str

    def fingerprint(self):
        for value, pattern in ((self.name, r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}'),
                               (self.image_id, r'sha256:[0-9a-f]{64}'),
                               (self.source_commit, r'[0-9a-f]{40}')):
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise ValueError('Explicit pinned local profile required')
        body = {'backend': 'local_acceptance', **asdict(self)}
        return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


@dataclass(frozen=True)
class Work:
    operation_key: str
    intent_id: str
    organization_id: str
    license_arn: str
    state: str
    epoch: int
    profile_digest: str


@dataclass(frozen=True)
class Lease:
    operation_key: str
    worker: str
    epoch: int
    token: str = field(repr=False)
    valid_until: datetime


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{32}', value):
        raise ValueError('Invalid internal operation key')
    return value


def seconds(value):
    if type(value) is not int or not 1 <= value <= 30:
        raise ValueError('Lease duration must be1..30 seconds')
    return value


class ProvisioningJournal:
    def __init__(self, licenses, profile, max_slots):
        if not isinstance(profile, LocalProfile) or type(max_slots) is not int or not 1 <= max_slots <= 256:
            raise ValueError('Explicit local profile and allocation-slot limit required')
        if licenses.db is not licenses.outbox.db:
            raise ValueError('License state and transaction database differ')
        self.profile_digest, self.max_slots = profile.fingerprint(), max_slots
        self.licenses, self.outbox, self.db = licenses, licenses.outbox, licenses.db
        with self.outbox.transaction():
            # The authenticated binding must already exist; do not bootstrap it.
            self.db.execute('SELECT id,license,org,state FROM provisioning_intents LIMIT 0')
            self.db.execute('''CREATE TABLE IF NOT EXISTS provisioning_work_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), profile TEXT NOT NULL, slots INTEGER NOT NULL)''')
            self.db.execute('INSERT OR IGNORE INTO provisioning_work_settings VALUES(1,?,?)',
                            (self.profile_digest, max_slots))
            if tuple(self.db.execute('SELECT profile,slots FROM provisioning_work_settings').fetchone()) != (self.profile_digest, max_slots):
                raise MeteringConflict('Provisioning profile/slot policy requires explicit migration')
            self.db.execute('''CREATE TABLE IF NOT EXISTS provisioning_work (
                operation TEXT PRIMARY KEY, intent TEXT NOT NULL UNIQUE, license TEXT NOT NULL UNIQUE,
                org TEXT NOT NULL, profile TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state IN ('reserved','leased','stop_requested')),
                epoch INTEGER NOT NULL CHECK(epoch>=0), worker TEXT, token TEXT, lease_until INTEGER,
                created INTEGER NOT NULL, updated INTEGER NOT NULL CHECK(updated>=created),
                CHECK((state='leased' AND worker IS NOT NULL AND token IS NOT NULL AND lease_until>updated)
                   OR (state<>'leased' AND worker IS NULL AND token IS NULL AND lease_until IS NULL)))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS provisioning_work_events (
                id INTEGER PRIMARY KEY, operation TEXT NOT NULL, epoch INTEGER NOT NULL,
                kind TEXT NOT NULL, at INTEGER NOT NULL, reason TEXT)''')

    def _audit(self, row, kind, at, reason=None):
        self.db.execute('INSERT INTO provisioning_work_events(operation,epoch,kind,at,reason) VALUES(?,?,?,?,?)',
                        (row['operation'], row['epoch'], kind, at, reason))

    @staticmethod
    def _work(row):
        return Work(row['operation'], row['intent'], row['org'], row['license'],
                    row['state'], row['epoch'], row['profile'])

    def _row(self, operation):
        row = self.db.execute('SELECT * FROM provisioning_work WHERE operation=?', (key(operation),)).fetchone()
        if row is None:
            raise MarketplaceDenied('Unknown provisioning work')
        if row['profile'] != self.profile_digest:
            raise MeteringConflict('Work profile changed')
        return row

    def inspect(self, operation):
        """Internal worker metadata only, never a buyer authorization API."""
        return self._work(self._row(operation))

    def _fresh(self, intent, clock):
        checked = self.licenses.check_pending(intent, clock=clock)
        if checked.intent_id != intent:
            raise MarketplaceUnavailable('Provisioning observation identity differs')
        return checked

    @staticmethod
    def _observed_now(checked, clock):
        # Must run after acquiring the write transaction: waiting for that lock
        # can exhaust the conservative observation window or an existing lease.
        now = clock()
        current = instant(now)
        if now < checked.checked_at or now >= checked.valid_until:
            raise MarketplaceUnavailable('Provisioning observation expired')
        return now, current

    def _binding(self, intent, now, checked=None, row=None):
        purchase, org = self.licenses._pending(intent, now)
        if ((checked is not None and (purchase, org) != (checked.purchase, checked.organization_id))
                or (row is not None and (intent, purchase.license_arn, org) != (row['intent'], row['license'], row['org']))):
            raise MeteringConflict('Provisioning purchase/organization mapping changed')
        return purchase, org

    @staticmethod
    def _monotone(row, current):
        if current < row['updated']:
            raise MarketplaceUnavailable('Provisioning clock moved backwards')

    def reserve(self, intent, *, clock=utc_now):
        checked = self._fresh(intent, clock)
        with self.outbox.transaction():
            now, current = self._observed_now(checked, clock)
            purchase, org = self._binding(intent, now, checked)
            row = self.db.execute('SELECT * FROM provisioning_work WHERE intent=?', (intent,)).fetchone()
            if row is not None:
                self._binding(intent, now, checked, row)
                self._monotone(row, current)
                if row['profile'] != self.profile_digest or row['state'] == 'stop_requested':
                    raise MarketplaceDenied('Work cannot be reserved again')
                return self._work(row)
            if self.db.execute('SELECT COUNT(*) FROM provisioning_work').fetchone()[0] >= self.max_slots:
                raise ProvisioningBusy('Allocation slots remain reserved pending reconciliation')
            operation = secrets.token_hex(16)
            self.db.execute('''INSERT INTO provisioning_work VALUES(?,?,?,?,?,'reserved',0,NULL,NULL,NULL,?,?)''',
                            (operation, intent, purchase.license_arn, org, self.profile_digest, current, current))
            row = self._row(operation)
            self._audit(row, 'reserved', current)
            return self._work(row)

    def _assert_lease(self, lease, now):
        if (not isinstance(lease, Lease) or not isinstance(lease.token, str)
                or not re.fullmatch(r'[0-9a-f]{32}', lease.token) or type(lease.epoch) is not int):
            raise MarketplaceDenied('Invalid work lease')
        current = instant(now)
        row = self._row(lease.operation_key)
        self._binding(row['intent'], now, row=row)
        self._monotone(row, current)
        if (row['state'] != 'leased' or row['token'] != lease.token or row['epoch'] != lease.epoch
                or row['worker'] != lease.worker or row['lease_until'] <= current):
            raise MarketplaceDenied('Work lease expired or superseded')
        return row

    def assert_current(self, lease, *, clock=utc_now):
        with self.outbox.transaction():
            return self._work(self._assert_lease(lease, clock()))

    @staticmethod
    def _lease(row):
        return Lease(row['operation'], row['worker'], row['epoch'], row['token'],
                     datetime.fromtimestamp(row['lease_until'], timezone.utc))

    def claim(self, operation, worker, *, lease_seconds=30, clock=utc_now):
        seconds(lease_seconds)
        if not isinstance(worker, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', worker):
            raise ValueError('Internal worker identifier required')
        intent = self._row(operation)['intent']
        checked = self._fresh(intent, clock)
        with self.outbox.transaction():
            now, current = self._observed_now(checked, clock)
            row = self._row(operation)
            self._binding(intent, now, checked, row)
            self._monotone(row, current)
            if row['state'] == 'stop_requested':
                raise MarketplaceDenied('Work has a stop fence')
            if row['state'] == 'leased' and row['lease_until'] > current:
                raise ProvisioningBusy('Work already has a live lease')
            until = min(current + lease_seconds, instant(checked.valid_until))
            self.db.execute('''UPDATE provisioning_work SET state='leased',epoch=epoch+1,
                worker=?,token=?,lease_until=?,updated=? WHERE operation=?''',
                (worker, secrets.token_hex(16), until, current, operation))
            row = self._row(operation)
            self._audit(row, 'claimed', current)
            return self._lease(row)

    def renew(self, lease, *, lease_seconds=30, clock=utc_now):
        seconds(lease_seconds)
        with self.outbox.transaction():
            row = self._assert_lease(lease, clock())
            intent = row['intent']
        checked = self._fresh(intent, clock)
        with self.outbox.transaction():
            now, current = self._observed_now(checked, clock)
            row = self._assert_lease(lease, now)
            self._binding(intent, now, checked, row)
            until = min(current + lease_seconds, instant(checked.valid_until))
            if (until, current) != (row['lease_until'], row['updated']):
                self.db.execute('UPDATE provisioning_work SET lease_until=?,updated=? WHERE operation=?',
                                (until, current, row['operation']))
                self._audit(row, 'renewed', current)
            return self._lease(self._row(row['operation']))

    def record_failure(self, lease, reason, *, clock=utc_now):
        if reason not in ('provider_unavailable', 'provisioning_failed', 'verification_failed'):
            raise ValueError('Fixed sanitized provisioning failure code required')
        with self.outbox.transaction():
            now = clock()
            row = self._assert_lease(lease, now)
            self.db.execute('''UPDATE provisioning_work SET state='reserved',worker=NULL,
                token=NULL,lease_until=NULL,updated=? WHERE operation=?''', (instant(now), row['operation']))
            self._audit(row, 'retry_reserved', instant(now), reason)

    def reconcile_stops(self, now):
        current, changed = instant(now), 0
        with self.outbox.transaction():
            rows = self.db.execute("SELECT * FROM provisioning_work WHERE state<>'stop_requested'").fetchall()
            for row in rows:
                if self.outbox.stop_info(row['license']) is not None:
                    at = max(current, row['updated'])
                    self.db.execute('''UPDATE provisioning_work SET state='stop_requested',epoch=epoch+1,
                        worker=NULL,token=NULL,lease_until=NULL,updated=? WHERE operation=?''', (at, row['operation']))
                    self._audit(self._row(row['operation']), 'stop_requested', at)
                    changed += 1
        return changed
