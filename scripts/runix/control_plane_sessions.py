"""Private short-lived browser sessions; not JWTs or API bearer credentials."""
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from control_plane_oidc import digest, fixed_url
from marketplace_adapter import MarketplaceDenied
from marketplace_metering import MeteringConflict, instant
from marketplace_registration import Principal, subject_id

TOKEN = re.compile(r'[A-Za-z0-9_-]{43}')
DENIED = 'Browser session denied'


def opaque(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def context_digest(value):
    if value is not None and (not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value)):
        raise ValueError('Pending context digest required')
    return value


@dataclass(frozen=True)
class SessionCredentials:
    token: str = field(repr=False)
    csrf: str = field(repr=False)
    expires: int


@dataclass(frozen=True)
class BrowserSession:
    principal: Principal
    token_digest: str = field(repr=False)
    csrf_digest: str = field(repr=False)
    pending: object = field(repr=False)


class BrowserSessions:
    def __init__(self, store, issuer, origin):
        fixed_url(issuer)
        if fixed_url(origin, local=True).path not in {'', '/'}:
            raise ValueError('Fixed browser origin required')
        self.store, self.issuer = store, issuer
        with store.transaction():
            store.db.execute('''CREATE TABLE IF NOT EXISTS browser_settings (
                id INTEGER PRIMARY KEY CHECK(id=1), issuer TEXT NOT NULL, origin TEXT NOT NULL)''')
            store.db.execute('INSERT OR IGNORE INTO browser_settings VALUES(1,?,?)', (issuer, origin))
            if tuple(store.db.execute('SELECT issuer,origin FROM browser_settings WHERE id=1').fetchone()) != (issuer, origin):
                raise MeteringConflict('Browser identity/origin configuration mismatch')
            store.db.execute('''CREATE TABLE IF NOT EXISTS browser_sessions (
                token TEXT PRIMARY KEY, subject TEXT NOT NULL, csrf TEXT NOT NULL,
                issued INTEGER NOT NULL, expires INTEGER NOT NULL, pending TEXT,
                revoked INTEGER)''')

    def issue(self, principal, now, *, pending=None, previous=None):
        stamp = instant(now)
        if not isinstance(principal, Principal) or principal.issuer != self.issuer:
            raise MarketplaceDenied(DENIED)
        try:
            subject_id(principal.subject)
            expiry = instant(principal.expires_at)
            if not stamp < expiry <= stamp + 900:
                raise ValueError()
            context_digest(pending)
        except (TypeError, ValueError):
            raise MarketplaceDenied(DENIED) from None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.store.transaction():
            self.store.db.execute('DELETE FROM browser_sessions WHERE expires<=?', (stamp,))
            if opaque(previous):
                self.store.db.execute('UPDATE browser_sessions SET revoked=? WHERE token=? AND revoked IS NULL',
                                      (stamp, digest(previous)))
            self.store.db.execute('INSERT INTO browser_sessions VALUES(?,?,?,?,?,?,NULL)',
                (digest(token), principal.subject, digest(csrf), stamp, expiry, pending))
        return SessionCredentials(token, csrf, expiry)

    def authenticate(self, token, now):
        if not opaque(token):
            raise MarketplaceDenied(DENIED)
        stamp = instant(now)
        row = self.store.db.execute('SELECT * FROM browser_sessions WHERE token=?', (digest(token),)).fetchone()
        if (not row or row['revoked'] is not None or not row['issued'] <= stamp < row['expires']
                or not 0 < row['expires'] - row['issued'] <= 900):
            raise MarketplaceDenied(DENIED)
        return BrowserSession(Principal(self.issuer, row['subject'], datetime.fromtimestamp(row['expires'], timezone.utc)),
                              row['token'], row['csrf'], row['pending'])

    def authorize_post(self, token, csrf_cookie, csrf_form, now):
        session = self.authenticate(token, now)
        if (not opaque(csrf_cookie) or not opaque(csrf_form)
                or not hmac.compare_digest(csrf_cookie, csrf_form)
                or not hmac.compare_digest(digest(csrf_cookie), session.csrf_digest)):
            raise MarketplaceDenied(DENIED)
        return session

    def revoke(self, token, now):
        stamp = instant(now)
        if not opaque(token):
            raise MarketplaceDenied(DENIED)
        with self.store.transaction():
            self.store.db.execute('UPDATE browser_sessions SET revoked=? WHERE token=? AND revoked IS NULL',
                                  (stamp, digest(token)))

    def clear_pending(self, token, expected, now):
        with self.store.transaction():
            session = self.authenticate(token, now)
            if session.pending is None or session.pending != context_digest(expected):
                raise MarketplaceDenied(DENIED)
            self.store.db.execute('UPDATE browser_sessions SET pending=NULL WHERE token=?', (session.token_digest,))
