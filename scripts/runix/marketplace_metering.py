"""Durable PAYG outbox for trusted workers; no HTTP API, collector or scheduler.

A caller must verify lifecycle, organization and provisioning before enqueue.
Nothing in this module makes a Purchase active or establishes buyer identity.
"""

import json
import os
import re
import sqlite3
import stat
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

from marketplace_adapter import MarketplaceDenied, Purchase, validate_purchase

UTC = timezone.utc
RETRYABLE = {"ThrottlingException", "InternalServiceErrorException", "RequestTimeout"}


class MeteringConflict(ValueError):
    pass


class MeteringProtocolError(ValueError):
    pass


def instant(value):
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None or value.microsecond):
        raise ValueError("Second-precision aware datetime required")
    return int(value.timestamp())


def deadline_for(timestamp):
    time = datetime.fromtimestamp(timestamp, UTC)
    following = (time.replace(day=28) + timedelta(days=4)).replace(
        day=1, hour=6, minute=0, second=0
    )
    return min(timestamp + 86400, instant(following))


@dataclass(frozen=True)
class Batch:
    token: str
    rows: tuple
    records: tuple


class MeteringOutbox:
    def __init__(self, path, seller_account, product_code):
        if (not isinstance(seller_account, str)
                or not re.fullmatch(r"[0-9]{12}", seller_account)
                or not isinstance(product_code, str) or not product_code.strip()):
            raise ValueError("Seller and product required")
        self.seller_account = seller_account
        self.product_code = product_code
        # Use a private operator-owned runtime directory, never a network share.
        # Do not silently reuse a world-readable DB or follow a final symlink.
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError("Metering database must be a private regular file")
        finally:
            os.close(descriptor)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            with self.transaction():
                self.db.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL, seller TEXT NOT NULL, product TEXT NOT NULL)")
                self.db.execute("INSERT OR IGNORE INTO settings VALUES(1,1,?,?)", (seller_account, product_code))
                config = self.db.execute("SELECT version,seller,product FROM settings").fetchone()
                if tuple(config) != (1, seller_account, product_code):
                    raise MeteringConflict("Database configuration mismatch")
                self.db.execute("""CREATE TABLE IF NOT EXISTS licenses (
                    license TEXT PRIMARY KEY, account TEXT NOT NULL,
                    agreement TEXT NOT NULL)""")
                self.db.execute("""CREATE TABLE IF NOT EXISTS usage (
                    id INTEGER PRIMARY KEY, license TEXT NOT NULL, dimension TEXT NOT NULL,
                    hour INTEGER NOT NULL, agreement TEXT NOT NULL, payload TEXT NOT NULL,
                    deadline INTEGER NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    lease TEXT, lease_until INTEGER, record_id TEXT, reason TEXT,
                    UNIQUE(license,dimension,hour))""")
                self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
                    token TEXT NOT NULL, usage_id INTEGER NOT NULL, started INTEGER NOT NULL,
                    outcome TEXT, PRIMARY KEY(token,usage_id))""")
                self.db.execute("""CREATE TABLE IF NOT EXISTS responses (
                    id INTEGER PRIMARY KEY, token TEXT NOT NULL, received INTEGER NOT NULL,
                    outcomes TEXT NOT NULL)""")
        except BaseException:
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    @staticmethod
    def record(row):
        record = json.loads(row["payload"])
        record["Timestamp"] = datetime.fromtimestamp(record["Timestamp"], UTC)
        return record

    def enqueue(self, purchase, dimension, timestamp, quantity, now, final_deadline=None):
        validate_purchase(purchase, self.product_code)
        if (not isinstance(dimension, str)
                or not re.fullmatch(r"[A-Za-z0-9_]{1,255}", dimension)
                or type(quantity) is not int or not 0 <= quantity <= 2147483647):
            raise ValueError("Invalid dimension or integer quantity")
        stamp, current = instant(timestamp), instant(now)
        if stamp > current:
            raise ValueError("Future usage is invalid")
        deadline = deadline_for(stamp)
        if final_deadline is not None:
            deadline = min(deadline, instant(final_deadline))
        if current >= deadline:
            raise ValueError("Usage reporting deadline passed")
        payload = json.dumps({
            "Timestamp": stamp, "CustomerAWSAccountId": purchase.account_id,
            "LicenseArn": purchase.license_arn, "Dimension": dimension,
            "Quantity": quantity,
        }, sort_keys=True, separators=(",", ":"))
        if len(payload.encode("utf-8")) > 32000:
            raise ValueError("Record exceeds the bounded request payload size")
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO licenses VALUES(?,?,?)",
                            (purchase.license_arn, purchase.account_id, purchase.agreement_id))
            identity = self.db.execute("SELECT account,agreement FROM licenses WHERE license=?",
                                       (purchase.license_arn,)).fetchone()
            if tuple(identity) != (purchase.account_id, purchase.agreement_id):
                raise MeteringConflict("License identity cannot be rebound")
            self.db.execute("""INSERT OR IGNORE INTO usage
                (license,dimension,hour,agreement,payload,deadline) VALUES(?,?,?,?,?,?)""",
                (purchase.license_arn, dimension, stamp // 3600, purchase.agreement_id, payload, deadline))
            row = self.db.execute("SELECT * FROM usage WHERE license=? AND dimension=? AND hour=?",
                                  (purchase.license_arn, dimension, stamp // 3600)).fetchone()
            if row["payload"] != payload or row["agreement"] != purchase.agreement_id:
                raise MeteringConflict("Sealed hourly record cannot be changed")
            # Replays can only tighten deadlines, never extend a cancellation window.
            self.db.execute("UPDATE usage SET deadline=MIN(deadline,?) WHERE id=?", (deadline, row["id"]))
            return row["id"]

    def shorten_deadline(self, license_arn, deadline):
        """Internal lifecycle hook; caller must authenticate/verify the end event."""
        value = instant(deadline)
        with self.transaction():
            self.db.execute("UPDATE usage SET deadline=MIN(deadline,?) WHERE license=? AND state!='accepted'",
                            (value, license_arn))

    def claim(self, now, lease_seconds=120):
        current = instant(now)
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 300:
            raise ValueError("Lease must be 1..300 seconds")
        token = uuid.uuid4().hex
        with self.transaction():
            self.db.execute("""UPDATE usage SET state='quarantined',reason='deadline_expired',lease=NULL,lease_until=NULL
                WHERE state IN ('pending','sending') AND deadline<=?""", (current,))
            rows = self.db.execute("""SELECT * FROM usage WHERE state='pending'
                OR (state='sending' AND lease_until<=?) ORDER BY deadline,id LIMIT 25""", (current,)).fetchall()
            for row in rows:
                if row["lease"]:
                    self.db.execute("UPDATE attempts SET outcome='lease_expired' WHERE token=? AND usage_id=? AND outcome IS NULL",
                                    (row["lease"], row["id"]))
                self.db.execute("UPDATE usage SET state='sending',lease=?,lease_until=? WHERE id=?",
                                (token, current + lease_seconds, row["id"]))
                self.db.execute("INSERT INTO attempts VALUES(?,?,?,NULL)", (token, row["id"], current))
        return Batch(token, tuple(row["id"] for row in rows), tuple(self.record(row) for row in rows))

    def _owned(self, batch, now):
        current = instant(now)
        rows = [self.db.execute("SELECT * FROM usage WHERE id=?", (key,)).fetchone() for key in batch.rows]
        return bool(rows) and all(
            row is not None and row["state"] == 'sending' and row["lease"] == batch.token
            and row["lease_until"] > current and row["deadline"] > current
            and self.record(row) == record
            for row, record in zip(rows, batch.records)
        ) and len(rows) == len(batch.records)

    def ready(self, batch, now):
        with self.transaction():
            return self._owned(batch, now)

    def finish(self, batch, response, now):
        """Atomically validate the entire response before any row changes."""
        expected = {self._key(record): (key, record) for key, record in zip(batch.rows, batch.records)}
        outcomes = {}
        if not isinstance(response, dict):
            raise MeteringProtocolError("Invalid metering response")
        for result in response.get("Results", []):
            record = result.get("UsageRecord", {})
            key = self._key(record)
            if key not in expected or expected[key][1] != record or key in outcomes:
                raise MeteringProtocolError("Foreign, changed or repeated response record")
            status, record_id = result.get("Status"), result.get("MeteringRecordId")
            if status == "Success":
                if not isinstance(record_id, str) or not record_id.strip():
                    raise MeteringProtocolError("Accepted usage needs a record ID")
                outcomes[key] = ("accepted", record_id, "Success")
            elif status in {"DuplicateRecord", "CustomerNotSubscribed"}:
                outcomes[key] = ("quarantined", None, status)
            else:
                raise MeteringProtocolError("Unknown metering result")
        for record in response.get("UnprocessedRecords", []):
            key = self._key(record)
            if key not in expected or expected[key][1] != record or key in outcomes:
                raise MeteringProtocolError("Invalid unprocessed record")
            outcomes[key] = ("pending", None, "Unprocessed")
        with self.transaction():
            # Keep valid AWS outcomes even if a lease/deadline elapsed in flight.
            # Reconciliation can then see remote acceptance without letting a
            # stale worker overwrite another worker's state.
            audit = [dict(usage_id=expected[key][0], state=value[0],
                          record_id=value[1], reason=value[2])
                     for key, value in outcomes.items()]
            self.db.execute("INSERT INTO responses(token,received,outcomes) VALUES(?,?,?)",
                            (batch.token, instant(now), json.dumps(audit, sort_keys=True)))
            if not self._owned(batch, now):
                return False
            for key, (row_id, _record) in expected.items():
                state, record_id, reason = outcomes.get(key, ("pending", None, "MissingResult"))
                self.db.execute("UPDATE usage SET state=?,record_id=?,reason=?,lease=NULL,lease_until=NULL WHERE id=?",
                                (state, record_id, reason, row_id))
                self.db.execute("UPDATE attempts SET outcome=? WHERE token=? AND usage_id=?",
                                (reason, batch.token, row_id))
        return True

    @staticmethod
    def _key(record):
        try:
            return (record["LicenseArn"], record["Dimension"], instant(record["Timestamp"]) // 3600)
        except (KeyError, TypeError, ValueError):
            raise MeteringProtocolError("Invalid echoed record identity") from None

    def failed(self, batch, reason, retryable, now):
        with self.transaction():
            if not self._owned(batch, now):
                return False
            for key in batch.rows:
                self.db.execute("UPDATE usage SET state=?,reason=?,lease=NULL,lease_until=NULL WHERE id=?",
                                ("pending" if retryable else "quarantined", reason, key))
                self.db.execute("UPDATE attempts SET outcome=? WHERE token=? AND usage_id=?", (reason, batch.token, key))
        return True

    def inspect(self, key):
        row = self.db.execute("SELECT * FROM usage WHERE id=?", (key,)).fetchone()
        return dict(row) if row else None


class MeteringWorker:
    """Explicit SDK worker; constructing it verifies seller via the normal session.

    Tests use botocore Stubber. Production use is gated on the missing lifecycle,
    usage collector and approved operational deployment, not just these tests.
    """

    def __init__(self, outbox, sts, metering):
        if sts.get_caller_identity().get("Account") != outbox.seller_account:
            raise MarketplaceDenied("AWS caller is not the configured seller")
        self.outbox, self.metering = outbox, metering

    def dispatch(self, clock):
        batch = self.outbox.claim(clock())
        if not batch.rows or not self.outbox.ready(batch, clock()):
            return 0
        try:
            response = self.metering.batch_meter_usage(UsageRecords=list(batch.records))
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "UnknownError")
            self.outbox.failed(batch, code, code in RETRYABLE, clock())
            return 0
        except BotoCoreError:
            self.outbox.failed(batch, "TransportError", True, clock())
            return 0
        self.outbox.finish(batch, response, clock())
        return len(batch.rows)
