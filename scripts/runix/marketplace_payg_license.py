"""Trusted PAYG event evidence and fresh checks; no resource provisioning."""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase
from marketplace_lifecycle import NegativeLifecycle, UPDATED
from marketplace_metering import MeteringConflict, instant


@dataclass(frozen=True)
class ProvisioningCheck:
    purchase: Purchase
    organization_id: str
    intent_id: str
    checked_at: datetime
    valid_until: datetime


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0)


class PaygLicenseState:
    def __init__(self, outbox, product_id, reader=None):
        if reader is not None and (
            reader.seller_account != outbox.seller_account
            or reader.product_code != outbox.product_code or reader.product_id != product_id
        ):
            raise ValueError('Agreement reader seller/product differs from the database')
        self.outbox, self.db, self.reader = outbox, outbox.db, reader
        self.negative = NegativeLifecycle(outbox, product_id)
        with outbox.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS payg_license_updates (
                license TEXT PRIMARY KEY, account TEXT NOT NULL, agreement TEXT NOT NULL,
                updated INTEGER NOT NULL, event_id TEXT NOT NULL UNIQUE)''')

    def record_update(self, event, now):
        """Trusted verified-origin worker only; JSON fields are not authentication."""
        parsed = self.negative._parse(event, now, allow_update=True)
        event_id, digest, kind, buyer, agreement, license_arn, updated, current = parsed
        if kind != UPDATED:
            raise ValueError('Use the negative reducer for ending events')
        purchase = Purchase(buyer, license_arn, self.outbox.product_code, agreement)
        with self.outbox.transaction():
            previous = self.db.execute('SELECT digest FROM lifecycle_events WHERE id=?', (event_id,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise MeteringConflict('Lifecycle event ID reused with a changed body')
                return False
            # This may precede registration, but it creates no organization,
            # membership, provisioning intent, active cluster or billable usage.
            self.outbox.bind_purchase(purchase)
            self.db.execute('''INSERT INTO payg_license_updates VALUES(?,?,?,?,?)
                ON CONFLICT(license) DO UPDATE SET updated=excluded.updated,event_id=excluded.event_id
                WHERE excluded.updated > payg_license_updates.updated''',
                (license_arn, buyer, agreement, updated, event_id))
            self.db.execute('INSERT INTO lifecycle_events VALUES(?,?,?,?,?,?,?,?)', parsed)
        return True

    def _pending(self, intent_id, now):
        current = instant(now)
        row = self.db.execute('''SELECT i.org,i.state,l.license,l.account,l.agreement
            FROM provisioning_intents i JOIN org_purchases p ON p.license=i.license AND p.org=i.org
            JOIN licenses l ON l.license=i.license WHERE i.id=?''', (intent_id,)).fetchone()
        if row is None or row['state'] != 'pending_license_verification':
            raise MarketplaceDenied('A bound pending provisioning intent is required')
        purchase = Purchase(row['account'], row['license'], self.outbox.product_code, row['agreement'])
        self.outbox.assert_not_stopped(purchase)
        update = self.db.execute('SELECT * FROM payg_license_updates WHERE license=?', (purchase.license_arn,)).fetchone()
        if (update is None or (update['account'], update['agreement']) != (purchase.account_id, purchase.agreement_id)
                or update['updated'] > current):
            raise MarketplaceDenied('A matching trusted license update is required')
        return purchase, row['org']

    def check_pending(self, intent_id, *, clock=utc_now):
        """Read-only eligibility evidence; a future real provisioner must recheck.

        No caller can pass this result to an API to allocate a resource. No
        pending intent is advanced or returned as successful provisioning here.
        """
        if not isinstance(intent_id, str) or not re.fullmatch(r'[0-9a-f]{32}', intent_id):
            raise MarketplaceDenied('Invalid provisioning intent identifier')
        if self.db.in_transaction:
            raise MarketplaceUnavailable('Fresh license checks require an outer transaction boundary')
        started = clock()
        instant(started)
        with self.outbox.transaction():
            purchase, org = self._pending(intent_id, started)
        if self.reader is None:
            raise MarketplaceUnavailable('Fresh agreement verification is not configured')
        # AWS calls never hold a SQLite write lock, so cancellation can commit
        # while this request is in flight.
        observation = self.reader.describe(purchase, started)
        finished = clock()
        instant(finished)
        valid_until = started + timedelta(seconds=30)
        if finished < started or finished >= valid_until:
            raise MarketplaceUnavailable('Fresh agreement observation window exceeded')
        if (observation.agreement_id != purchase.agreement_id or observation.observed_at != started
                or observation.status != 'ACTIVE' or observation.starts_at > finished
                or (observation.ends_at is not None and observation.ends_at <= finished)):
            raise MarketplaceDenied('Agreement is not currently active')
        if observation.ends_at is not None:
            valid_until = min(valid_until, observation.ends_at)
        with self.outbox.transaction():
            current_purchase, current_org = self._pending(intent_id, finished)
            if (current_purchase, current_org) != (purchase, org):
                raise MarketplaceDenied('Pending purchase binding changed during verification')
        return ProvisioningCheck(purchase, org, intent_id, finished, valid_until)
