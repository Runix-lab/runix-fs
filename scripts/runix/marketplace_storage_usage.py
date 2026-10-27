"""Exact storage byte-time accounting for trusted, completed usage intervals.

No storage collector, buyer API or subscription verification is implemented.
Never feed estimated samples or buyer-supplied values into this ledger.
"""

import re
from datetime import datetime, timezone

from marketplace_adapter import validate_purchase
from marketplace_metering import MeteringConflict, instant

DIMENSION = 'storage_gib_hour'
BYTE_SECONDS_PER_UNIT = (1 << 30) * 3600
UTC = timezone.utc


class StorageUsageLedger:
    def __init__(self, outbox):
        self.outbox = outbox
        self.db = outbox.db
        with outbox.transaction():
            self.db.execute('''CREATE TABLE IF NOT EXISTS storage_streams (
                license TEXT PRIMARY KEY, started INTEGER NOT NULL,
                observed INTEGER NOT NULL, sealed INTEGER NOT NULL,
                remainder TEXT NOT NULL DEFAULT '0', waived TEXT NOT NULL DEFAULT '0',
                closed INTEGER NOT NULL DEFAULT 0)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS storage_intervals (
                license TEXT NOT NULL, event TEXT NOT NULL, started INTEGER NOT NULL,
                ended INTEGER NOT NULL, bytes TEXT NOT NULL,
                PRIMARY KEY(license,event))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS storage_hours (
                license TEXT NOT NULL, hour INTEGER NOT NULL, byte_seconds TEXT NOT NULL,
                PRIMARY KEY(license,hour))''')

    def _stream(self, purchase):
        self.outbox.bind_purchase(purchase)
        row = self.db.execute('SELECT * FROM storage_streams WHERE license=?',
                              (purchase.license_arn,)).fetchone()
        if row is None:
            raise MeteringConflict('Usage requires explicit verified-service activation')
        return row

    def activate(self, purchase, started, now):
        """Trusted lifecycle hook; does not itself verify a license or provision."""
        start, current = instant(started), instant(now)
        if start < 0 or start > current:
            raise ValueError('Activation must be a past or current service time')
        with self.outbox.transaction():
            self.outbox.bind_purchase(purchase)
            existing = self.db.execute('SELECT * FROM storage_streams WHERE license=?',
                                       (purchase.license_arn,)).fetchone()
            if existing is not None:
                if existing['started'] != start:
                    raise MeteringConflict('Activation cannot be moved or restarted')
                return dict(existing)
            if self.db.execute('SELECT 1 FROM usage WHERE license=? AND dimension=?',
                               (purchase.license_arn, DIMENSION)).fetchone():
                raise MeteringConflict('Cannot mix manual storage records and interval accounting')
            self.db.execute('''INSERT INTO storage_streams(license,started,observed,sealed)
                VALUES(?,?,?,?)''', (purchase.license_arn, start, start, start))
            return dict(self._stream(purchase))

    def append(self, purchase, source_event, start, end, logical_bytes, now):
        """Append a proven constant-usage interval; reject unknown gaps/overlap."""
        left, right, current = instant(start), instant(end), instant(now)
        if (not isinstance(source_event, str)
                or not re.fullmatch(r'[A-Za-z0-9_:.\-]{1,128}', source_event)
                or type(logical_bytes) is not int or not 0 <= logical_bytes <= (1 << 63) - 1
                or left < 0 or not 0 < right - left <= 3600 or right > current):
            raise ValueError('Invalid completed usage interval')
        with self.outbox.transaction():
            stream = self._stream(purchase)
            previous = self.db.execute('''SELECT started,ended,bytes FROM storage_intervals
                WHERE license=? AND event=?''', (purchase.license_arn, source_event)).fetchone()
            if previous is not None:
                if tuple(previous) != (left, right, str(logical_bytes)):
                    raise MeteringConflict('Source event replay changed its usage')
                return False
            if stream['closed'] or left != stream['observed']:
                raise MeteringConflict('Usage stream closed, missing interval or out of order')
            self.db.execute('INSERT INTO storage_intervals VALUES(?,?,?,?,?)',
                            (purchase.license_arn, source_event, left, right, str(logical_bytes)))
            cursor = left
            while cursor < right:
                hour = cursor // 3600
                boundary = min(right, (hour + 1) * 3600)
                previous = self.db.execute('''SELECT byte_seconds FROM storage_hours
                    WHERE license=? AND hour=?''', (purchase.license_arn, hour)).fetchone()
                total = (int(previous[0]) if previous else 0) + logical_bytes * (boundary - cursor)
                self.db.execute('''INSERT INTO storage_hours VALUES(?,?,?)
                    ON CONFLICT(license,hour) DO UPDATE SET byte_seconds=excluded.byte_seconds''',
                    (purchase.license_arn, hour, str(total)))
                cursor = boundary
            self.db.execute('UPDATE storage_streams SET observed=? WHERE license=?',
                            (right, purchase.license_arn))
            return True

    def seal(self, purchase, through, now, *, final=False, final_deadline=None):
        """Atomically freeze observed usage, carry and outbox rows; no AWS call."""
        cutoff, current = instant(through), instant(now)
        if (type(final) is not bool or cutoff > current
                or (not final and cutoff % 3600)):
            raise ValueError('Seal requires a completed UTC hour or final partial hour')
        with self.outbox.transaction():
            stream = self._stream(purchase)
            if cutoff < stream['sealed'] or cutoff > stream['observed']:
                raise MeteringConflict('Unobserved or stale seal boundary')
            if stream['closed']:
                if cutoff != stream['sealed']:
                    raise MeteringConflict('Closed stream cannot be extended')
                return dict(stream)
            if final and cutoff != stream['observed']:
                raise MeteringConflict('Final settlement must end at observed boundary')
            if cutoff - stream['sealed'] > 86400:
                raise MeteringConflict('Seal backlog exceeds bounded hourly reporting')
            remainder = int(stream['remainder'])
            cursor = stream['sealed']
            while cursor < cutoff:
                hour = cursor // 3600
                boundary = min(cutoff, (hour + 1) * 3600)
                row = self.db.execute('''SELECT byte_seconds FROM storage_hours
                    WHERE license=? AND hour=?''', (purchase.license_arn, hour)).fetchone()
                if row is None:
                    raise MeteringConflict('Missing authoritative usage coverage')
                quantity, remainder = divmod(remainder + int(row[0]), BYTE_SECONDS_PER_UNIT)
                timestamp = datetime.fromtimestamp(max(hour * 3600, stream['started']), UTC)
                self.outbox.enqueue(purchase, DIMENSION, timestamp, quantity, now,
                                    final_deadline=final_deadline)
                cursor = boundary
            waived = remainder if final else int(stream['waived'])
            self.db.execute('''UPDATE storage_streams SET sealed=?,remainder=?,waived=?,closed=?
                WHERE license=?''', (cutoff, str(0 if final else remainder), str(waived),
                                    int(final), purchase.license_arn))
            if final_deadline is not None:
                self.outbox.shorten_deadline(purchase.license_arn, final_deadline)
            return dict(self._stream(purchase))

    def status(self, purchase):
        validate_purchase(purchase, self.outbox.product_code)
        with self.outbox.transaction():
            return dict(self._stream(purchase))
