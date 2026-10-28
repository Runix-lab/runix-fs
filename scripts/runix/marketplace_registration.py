"""Private pending purchase registry, without HTTP or an identity provider.

Principal must come from verified authentication middleware. Constructing it
is not authentication. Membership administration is operator-only; expose none
of this module directly as a buyer-controlled arbitrary method dispatcher.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from urllib.parse import urlsplit

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase
from marketplace_metering import MeteringConflict, instant


@dataclass(frozen=True)
class Principal:
    issuer: str
    subject: str
    expires_at: object


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('Invalid organization identifier')
    return value


def subject_id(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 255
            or any(ord(char) < 32 for char in value)):
        raise ValueError('Invalid authenticated subject')
    return value


class RegistrationRegistry:
    def __init__(self, outbox, gateway, issuer):
        parsed = urlsplit(issuer)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or len(issuer) > 2048):
            raise ValueError('A fixed HTTPS authentication issuer is required')
        if gateway is not None and (gateway.product_code != outbox.product_code
                or gateway.seller_account != outbox.seller_account):
            raise ValueError('Resolver and database seller/product differ')
        self.outbox, self.gateway, self.issuer = outbox, gateway, issuer
        self.db = outbox.db
        with outbox.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS registration_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), issuer TEXT NOT NULL)''')
            self.db.execute('INSERT OR IGNORE INTO registration_settings VALUES(1,?)', (issuer,))
            if self.db.execute('SELECT issuer FROM registration_settings').fetchone()[0] != issuer:
                raise MeteringConflict('Authentication issuer cannot silently change')
            self.db.execute('''CREATE TABLE IF NOT EXISTS org_memberships (
                org TEXT NOT NULL, subject TEXT NOT NULL, role TEXT NOT NULL,
                PRIMARY KEY(org,subject))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS registration_claims (
                digest TEXT PRIMARY KEY, license TEXT NOT NULL, issued INTEGER NOT NULL,
                expires INTEGER NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS org_purchases (
                license TEXT PRIMARY KEY, org TEXT NOT NULL, bound INTEGER NOT NULL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS provisioning_intents (
                id TEXT PRIMARY KEY, license TEXT NOT NULL UNIQUE, org TEXT NOT NULL,
                state TEXT NOT NULL CHECK(state='pending_license_verification'))''')

    def set_membership(self, org, subject, role):
        """Trusted operator bootstrap/revocation, never an unauthenticated route."""
        identifier(org)
        subject_id(subject)
        if role not in {'owner', 'admin', 'member', None}:
            raise ValueError('Unsupported organization role')
        with self.outbox.transaction():
            if role is None:
                self.db.execute('DELETE FROM org_memberships WHERE org=? AND subject=?', (org, subject))
            else:
                self.db.execute('''INSERT INTO org_memberships VALUES(?,?,?)
                    ON CONFLICT(org,subject) DO UPDATE SET role=excluded.role''', (org, subject, role))

    def _authenticated_subject(self, principal, now):
        if not isinstance(principal, Principal) or principal.issuer != self.issuer:
            raise MarketplaceDenied('Verified authentication context required')
        try:
            subject_id(principal.subject)
            expiry = instant(principal.expires_at)
            current = instant(now)
        except (ValueError, TypeError):
            raise MarketplaceDenied('Invalid authentication context') from None
        if expiry <= current or expiry - current > 900:
            raise MarketplaceDenied('Expired or excessively long authentication context')
        return principal.subject

    def _authorize(self, principal, org, now, admin=False):
        identifier(org)
        self._authenticated_subject(principal, now)
        row = self.db.execute('SELECT role FROM org_memberships WHERE org=? AND subject=?',
                              (org, principal.subject)).fetchone()
        if row is None or (admin and row[0] not in {'owner', 'admin'}):
            raise MarketplaceDenied('Organization membership/administration required')

    def register(self, aws_token, now, ttl_seconds=600):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError('Registration claim TTL must be 1..900 seconds')
        current = instant(now)
        if self.gateway is None:
            raise MarketplaceUnavailable('Marketplace registration unavailable')
        # Resolve before persisting. Neither the raw token nor its hash is stored.
        purchase = self.gateway.resolve_registration(aws_token)
        claim = secrets.token_urlsafe(32)
        digest = hashlib.sha256(claim.encode('ascii')).hexdigest()
        with self.outbox.transaction():
            self.outbox.bind_purchase(purchase)
            self.outbox.assert_not_stopped(purchase)
            self.db.execute('INSERT INTO registration_claims VALUES(?,?,?,?)',
                            (digest, purchase.license_arn, current, current + ttl_seconds))
        return claim

    def bind(self, principal, org, claim, now):
        if not isinstance(claim, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', claim):
            raise MarketplaceDenied('Invalid registration claim')
        digest = hashlib.sha256(claim.encode('ascii')).hexdigest()
        current = instant(now)
        with self.outbox.transaction():
            self._authorize(principal, org, now, admin=True)
            row = self.db.execute('SELECT * FROM registration_claims WHERE digest=?', (digest,)).fetchone()
            if row is None or not row['issued'] <= current < row['expires']:
                raise MarketplaceDenied('Unknown or expired registration claim')
            if self.outbox.stop_info(row['license']):
                raise MarketplaceDenied('Subscription stopped; binding denied')
            existing = self.db.execute('SELECT * FROM org_purchases WHERE license=?', (row['license'],)).fetchone()
            if existing is not None and existing['org'] != org:
                raise MarketplaceDenied('Purchase already belongs to an organization')
            self.db.execute('INSERT OR IGNORE INTO org_purchases VALUES(?,?,?)',
                            (row['license'], org, current))
            self.db.execute('''INSERT OR IGNORE INTO provisioning_intents VALUES(?,?,?,?)''',
                            (uuid.uuid4().hex, row['license'], org, 'pending_license_verification'))
            intent = self.db.execute('SELECT * FROM provisioning_intents WHERE license=?',
                                     (row['license'],)).fetchone()
            if intent is None or intent['org'] != org:
                raise MeteringConflict('Binding and pending intent identity differ')
            return dict(intent)

    def list_purchases(self, principal, org, now):
        with self.outbox.transaction():
            self._authorize(principal, org, now)
            rows = self.db.execute('''SELECT p.license, l.account, l.agreement, i.state
                FROM org_purchases p JOIN licenses l ON l.license=p.license
                JOIN provisioning_intents i ON i.license=p.license
                WHERE p.org=? ORDER BY p.license''', (org,)).fetchall()
            result = []
            for row in rows:
                value = dict(row)
                if self.outbox.stop_info(row['license']):
                    value['state'] = 'stopped_reconciliation'
                result.append(value)
            return result

    def list_organizations(self, principal, now):
        with self.outbox.transaction():
            subject = self._authenticated_subject(principal, now)
            rows = self.db.execute('SELECT org,role FROM org_memberships WHERE subject=? ORDER BY org',
                                   (subject,)).fetchall()
            return [dict(row) for row in rows]
