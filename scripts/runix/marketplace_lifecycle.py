"""Negative-event reducer for a trusted future EventBridge/SQS worker.

JSON shape checks do not authenticate AWS. No public webhook, AWS queue,
positive activation, deletion or resource-access revocation is implemented.
"""

import hashlib
import json
import re
import uuid
from datetime import datetime

from marketplace_adapter import MarketplaceDenied, Purchase, validate_purchase
from marketplace_metering import MeteringConflict, instant

ENDED = {'Purchase Agreement Ended - Manufacturer', 'Purchase Agreement Ended - Proposer'}
DEPROVISIONED = 'License Deprovisioned - Manufacturer'
TERMINAL = {'ARCHIVED', 'CANCELLED', 'EXPIRED', 'RENEWED', 'REPLACED',
            'ROLLED_BACK', 'SUPERSEDED', 'TERMINATED'}


def object_field(value, key):
    result = value.get(key)
    if not isinstance(result, dict):
        raise ValueError('Missing lifecycle event object')
    return result


def event_time(value):
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError('Invalid event timestamp')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        stamp = instant(parsed.replace(microsecond=0))
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Invalid event timestamp') from None
    if stamp < 0:
        raise ValueError('Invalid event timestamp')
    return stamp


class NegativeLifecycle:
    def __init__(self, outbox, product_id):
        if not isinstance(product_id, str) or not re.fullmatch(r'prod-[A-Za-z0-9]+', product_id):
            raise ValueError('Configured Marketplace product ID required')
        self.outbox, self.db, self.product_id = outbox, outbox.db, product_id
        with outbox.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS lifecycle_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), product TEXT NOT NULL)''')
            self.db.execute('INSERT OR IGNORE INTO lifecycle_settings VALUES(1,?)', (product_id,))
            if self.db.execute('SELECT product FROM lifecycle_settings').fetchone()[0] != product_id:
                raise MeteringConflict('Lifecycle product mapping cannot change')
            self.db.execute('''CREATE TABLE IF NOT EXISTS lifecycle_events (
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, kind TEXT NOT NULL,
                account TEXT NOT NULL, agreement TEXT NOT NULL, license TEXT,
                cutoff INTEGER NOT NULL, received INTEGER NOT NULL)''')

    def _parse(self, event, now):
        if not isinstance(event, dict):
            raise ValueError('Expected structured EventBridge event')
        current = instant(now)
        if (event.get('version') != '0' or event.get('source') != 'aws.agreement-marketplace'
                or event.get('account') != self.outbox.seller_account
                or event.get('region') != 'us-east-1'):
            raise MarketplaceDenied('Foreign lifecycle event envelope')
        kind = event.get('detail-type')
        if not isinstance(kind, str) or kind not in ENDED | {DEPROVISIONED}:
            raise ValueError('Unsupported event; no activation is inferred')
        event_id = event.get('id')
        try:
            if not isinstance(event_id, str) or str(uuid.UUID(event_id)) != event_id:
                raise ValueError('Invalid event ID')
        except (ValueError, AttributeError):
            raise ValueError('Invalid event ID') from None
        cutoff = event_time(event.get('time'))
        if cutoff > current:
            raise ValueError('Future lifecycle event needs reconciliation')
        detail = object_field(event, 'detail')
        if detail.get('catalog') != 'AWSMarketplace':
            raise MarketplaceDenied('Foreign event catalog')
        agreement = object_field(detail, 'agreement')
        agreement_id = agreement.get('id')
        if not isinstance(agreement_id, str) or not re.fullmatch(r'agmt-[A-Za-z0-9]+', agreement_id):
            raise ValueError('Invalid agreement identity')
        resources = event.get('resources')
        expected_resource = 'arn:aws:aws-marketplace::aws:agreement:' + agreement_id
        if not isinstance(resources, list) or expected_resource not in resources:
            raise MarketplaceDenied('Agreement resource mismatch')
        buyer = object_field(detail, 'acceptor').get('accountId')
        if not isinstance(buyer, str) or not re.fullmatch(r'[0-9]{12}', buyer):
            raise ValueError('Invalid buyer identity')
        if object_field(detail, 'proposer').get('accountId') != self.outbox.seller_account:
            raise MarketplaceDenied('Only configured direct-sale proposer is supported')
        product = detail.get('product')
        if kind == DEPROVISIONED or product is not None:
            if not isinstance(product, dict):
                raise ValueError('Product mapping required')
            if product.get('id') != self.product_id:
                raise MarketplaceDenied('Foreign product ID')
            if ('code' in product or kind == DEPROVISIONED) and product.get('code') != self.outbox.product_code:
                raise MarketplaceDenied('Foreign product code')
        license_arn = None
        if kind == DEPROVISIONED:
            license_arn = object_field(detail, 'license').get('arn')
            validate_purchase(Purchase(buyer, license_arn, self.outbox.product_code, agreement_id), self.outbox.product_code)
        else:
            if agreement.get('status') not in TERMINAL:
                raise ValueError('Agreement-ended event must have terminal status')
            if agreement.get('endTime') is not None:
                cutoff = min(cutoff, event_time(agreement['endTime']))
        try:
            encoded = json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
        except (TypeError, ValueError):
            raise ValueError('Invalid JSON event') from None
        if len(encoded) > 256 * 1024:
            raise ValueError('Lifecycle event is too large')
        return event_id, hashlib.sha256(encoded).hexdigest(), kind, buyer, agreement_id, license_arn, cutoff, current

    def apply(self, event, now):
        """Apply only after transport origin verification by the trusted worker."""
        parsed = self._parse(event, now)
        event_id, digest, kind, buyer, agreement, license_arn, cutoff, current = parsed
        with self.outbox.transaction():
            previous = self.db.execute('SELECT digest FROM lifecycle_events WHERE id=?', (event_id,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise MeteringConflict('Lifecycle event ID reused with a changed body')
                return False
            if license_arn:
                for table in ('licenses', 'license_stops'):
                    row = self.db.execute(f'SELECT account,agreement FROM {table} WHERE license=?', (license_arn,)).fetchone()
                    if row and tuple(row) != (buyer, agreement):
                        raise MarketplaceDenied('License event identity mismatch')
                self.db.execute('''INSERT INTO license_stops VALUES(?,?,?,?)
                    ON CONFLICT(license) DO UPDATE SET cutoff=MIN(cutoff,excluded.cutoff)''',
                    (license_arn, buyer, agreement, cutoff))
            else:
                known = self.db.execute('SELECT DISTINCT account FROM licenses WHERE agreement=?',
                                        (agreement,)).fetchall()
                if any(row[0] != buyer for row in known):
                    raise MarketplaceDenied('Agreement buyer identity mismatch')
                # Agreement tombstones precede registration safely; they never grant access.
                self.db.execute('''INSERT INTO agreement_stops VALUES(?,?,?)
                    ON CONFLICT(account,agreement) DO UPDATE SET cutoff=MIN(cutoff,excluded.cutoff)''',
                    (buyer, agreement, cutoff))
            self.db.execute('INSERT INTO lifecycle_events VALUES(?,?,?,?,?,?,?,?)', parsed)
            self.outbox.quarantine_stopped()
        return True
