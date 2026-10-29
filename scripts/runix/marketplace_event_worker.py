"""SDK-backed lifecycle polling with a narrow deployment-profile preflight.

No infrastructure creation or public webhook. Real AWS origin/IAM validation
and deployment review remain required; JSON/MD5 is not producer authentication.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable
from marketplace_lifecycle import ENDED, DEPROVISIONED, UPDATED
from marketplace_metering import MeteringOutbox
from marketplace_payg_license import PaygLicenseState, utc_now

KINDS = sorted(ENDED | {DEPROVISIONED, UPDATED})
ATTRIBUTES = ['QueueArn', 'Policy', 'VisibilityTimeout', 'MessageRetentionPeriod',
              'RedrivePolicy', 'RedriveAllowPolicy', 'SqsManagedSseEnabled']


def strict_json(value, maximum=65536):
    def unique(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = item
        return result
    def invalid_constant(_value):
        raise ValueError('Nonfinite JSON constant')
    if not isinstance(value, str) or not value or len(value.encode('utf-8')) > maximum:
        raise ValueError('Invalid JSON size/type')
    try:
        return json.loads(value, object_pairs_hook=unique, parse_constant=invalid_constant)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError('Malformed JSON') from None


def queue_policy(queue_arn, rule_arn, seller):
    """Expected offline policy profile; never installs or modifies a policy."""
    return {'Version': '2012-10-17', 'Statement': [
        {'Sid': 'PinnedEventBridge', 'Effect': 'Allow',
         'Principal': {'Service': 'events.amazonaws.com'}, 'Action': 'sqs:SendMessage',
         'Resource': queue_arn, 'Condition': {'ArnEquals': {'aws:SourceArn': rule_arn},
                                            'StringEquals': {'aws:SourceAccount': seller}}},
        {'Sid': 'DenyOtherSources', 'Effect': 'Deny', 'Principal': '*',
         'Action': 'sqs:SendMessage', 'Resource': queue_arn,
         'Condition': {'ArnNotEquals': {'aws:SourceArn': rule_arn}}},
    ]}


def event_pattern(seller, product_id, product_code):
    return {'source': ['aws.agreement-marketplace'], 'account': [seller],
            'region': ['us-east-1'], '$or': [
                {'detail-type': sorted({UPDATED, DEPROVISIONED}),
                 'detail': {'product': {'id': [product_id], 'code': [product_code]}}},
                {'detail-type': sorted(ENDED),
                 'detail': {'product': {'id': [product_id, {'exists': False}]}}},
            ]}


@dataclass(frozen=True)
class EventTransport:
    queue_url: str
    queue_arn: str
    rule_arn: str
    consumer_role_arn: str
    processing_dlq_arn: str
    delivery_dlq_arn: str

    def validate(self, seller):
        queue_pattern = rf'arn:aws:sqs:us-east-1:{seller}:[A-Za-z0-9_-]{{1,80}}'
        arns = (self.queue_arn, self.processing_dlq_arn, self.delivery_dlq_arn)
        if (any(not isinstance(arn, str) or not re.fullmatch(queue_pattern, arn) for arn in arns)
                or len(set(arns)) != 3
                or self.queue_url != self.url(self.queue_arn)
                or not isinstance(self.rule_arn, str)
                or not re.fullmatch(rf'arn:aws:events:us-east-1:{seller}:rule/[A-Za-z0-9_.-]{{1,64}}', self.rule_arn)
                or not isinstance(self.consumer_role_arn, str)
                or not re.fullmatch(rf'arn:aws:iam::{seller}:role/[A-Za-z0-9+=,.@_-]{{1,64}}', self.consumer_role_arn)):
            raise ValueError('Invalid pinned same-account event transport')

    @staticmethod
    def url(arn):
        fields = arn.split(':')
        return 'https://sqs.us-east-1.amazonaws.com/' + fields[4] + '/' + fields[5]


@dataclass(frozen=True)
class PollResult:
    persisted: bool
    duplicate: bool = False
    delete_requested: bool = False


class SqsLifecycleWorker:
    def __init__(self, sts, sqs, events, state, transport):
        transport.validate(state.outbox.seller_account)
        self.sts, self.sqs, self.events = sts, sqs, events
        self.state, self.transport = state, transport
        self.seller = state.outbox.seller_account

    @classmethod
    def from_session(cls, session, state, transport):
        clients = [session.client(service, region_name='us-east-1', config=Config(
            connect_timeout=3, read_timeout=20,
            retries={'mode': 'standard', 'total_max_attempts': 2},
            ignore_configured_endpoint_urls=True,
        )) for service in ('sts', 'sqs', 'events')]
        return cls(*clients, state, transport)

    @staticmethod
    def _call(operation, **parameters):
        try:
            return operation(**parameters)
        except (BotoCoreError, ClientError):
            raise MarketplaceUnavailable('AWS event transport request failed') from None

    def _attributes(self, arn):
        attributes = self._call(self.sqs.get_queue_attributes,
            QueueUrl=self.transport.url(arn), AttributeNames=ATTRIBUTES).get('Attributes', {})
        if (attributes.get('QueueArn') != arn or attributes.get('SqsManagedSseEnabled') != 'true'
                or attributes.get('MessageRetentionPeriod') != ('345600' if arn == self.transport.queue_arn else '1209600')):
            raise MarketplaceDenied('Queue identity/encryption/retention profile mismatch')
        return attributes

    def _send_policy(self, attributes, arn):
        actual = strict_json(attributes.get('Policy'))
        if actual != queue_policy(arn, self.transport.rule_arn, self.seller):
            raise MarketplaceDenied('Queue send policy differs from pinned profile')

    def preflight(self):
        t = self.transport
        identity = self._call(self.sts.get_caller_identity)
        role_name = t.consumer_role_arn.rsplit('/', 1)[1]
        arn = identity.get('Arn')
        if (identity.get('Account') != self.seller or not isinstance(arn, str)
                or not re.fullmatch(rf'arn:aws:sts::{self.seller}:assumed-role/{re.escape(role_name)}/[A-Za-z0-9_=,.@-]{{2,64}}', arn)):
            raise MarketplaceDenied('Pinned seller consumer role is required')
        main = self._attributes(t.queue_arn)
        self._send_policy(main, t.queue_arn)
        redrive = strict_json(main.get('RedrivePolicy'))
        if (main.get('VisibilityTimeout') != '60'
                or not isinstance(redrive, dict)
                or set(redrive) != {'deadLetterTargetArn', 'maxReceiveCount'}
                or redrive.get('deadLetterTargetArn') != t.processing_dlq_arn
                or type(redrive.get('maxReceiveCount')) not in {int, str}
                or str(redrive['maxReceiveCount']) != '3'):
            raise MarketplaceDenied('Queue visibility/redrive profile mismatch')
        processing = self._attributes(t.processing_dlq_arn)
        if strict_json(processing.get('RedriveAllowPolicy')) != {
            'redrivePermission': 'byQueue', 'sourceQueueArns': [t.queue_arn],
        }:
            raise MarketplaceDenied('Processing dead-letter source profile mismatch')
        delivery = self._attributes(t.delivery_dlq_arn)
        self._send_policy(delivery, t.delivery_dlq_arn)
        rule_name = t.rule_arn.rsplit('/', 1)[1]
        rule = self._call(self.events.describe_rule, Name=rule_name, EventBusName='default')
        pattern = event_pattern(self.seller, self.state.negative.product_id, self.state.outbox.product_code)
        if (rule.get('Arn') != t.rule_arn or rule.get('Name') != rule_name
                or rule.get('State') != 'ENABLED' or rule.get('EventBusName') != 'default'
                or rule.get('ScheduleExpression') or rule.get('RoleArn')
                or strict_json(rule.get('EventPattern')) != pattern):
            raise MarketplaceDenied('EventBridge rule differs from pinned profile')
        targets = self._call(self.events.list_targets_by_rule,
                            Rule=rule_name, EventBusName='default', Limit=100)
        items = targets.get('Targets')
        if targets.get('NextToken') or not isinstance(items, list) or len(items) != 1:
            raise MarketplaceDenied('Expected one direct queue target')
        target = items[0]
        if (set(target) != {'Id', 'Arn', 'DeadLetterConfig', 'RetryPolicy'}
                or target.get('Arn') != t.queue_arn
                or not isinstance(target.get('Id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', target['Id'])
                or target.get('DeadLetterConfig') != {'Arn': t.delivery_dlq_arn}
                or target.get('RetryPolicy') != {'MaximumRetryAttempts': 185, 'MaximumEventAgeInSeconds': 86400}):
            raise MarketplaceDenied('Unexpected target, transformation or delivery retry profile')

    def run_once(self, *, clock=utc_now):
        self.preflight()
        result = self._call(self.sqs.receive_message, QueueUrl=self.transport.queue_url,
            MaxNumberOfMessages=1, WaitTimeSeconds=10, VisibilityTimeout=60,
            MessageSystemAttributeNames=['ApproximateReceiveCount', 'SentTimestamp'])
        messages = result.get('Messages', [])
        if not isinstance(messages, list) or len(messages) > 1:
            raise ValueError('Unexpected queue response')
        if not messages:
            return PollResult(False)
        self.preflight()
        message = messages[0]
        body = message.get('Body')
        handle = message.get('ReceiptHandle')
        message_id = message.get('MessageId')
        if (not isinstance(handle, str) or not 1 <= len(handle) <= 4096
                or not isinstance(message_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', message_id)
                or not isinstance(body, str) or not 1 <= len(body.encode('utf-8')) <= 256 * 1024
                or message.get('MD5OfBody') != hashlib.md5(body.encode('utf-8'), usedforsecurity=False).hexdigest()):
            raise ValueError('Invalid queue message envelope/checksum')
        event = strict_json(body, maximum=256 * 1024)
        if not isinstance(event, dict) or event.get('detail-type') not in KINDS:
            raise ValueError('Unsupported queue event')
        now = clock()
        if event['detail-type'] == UPDATED:
            applied = self.state.record_update(event, now)
        else:
            applied = self.state.negative.apply(event, now)
        # The reducer committed before this API call. Old handles and even
        # successful SQS deletes may redeliver; immutable event IDs remain key.
        self._call(self.sqs.delete_message, QueueUrl=self.transport.queue_url, ReceiptHandle=handle)
        return PollResult(True, duplicate=not applied, delete_requested=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    box = None
    try:
        config_path = Path(args.config)
        if config_path.stat().st_size > 16384:
            raise ValueError('Oversized worker configuration')
        config = strict_json(config_path.read_text())
        fields = set(EventTransport.__dataclass_fields__)
        if not isinstance(config, dict) or set(config) != fields | {'database', 'seller_account', 'product_code', 'product_id'}:
            raise ValueError('Invalid worker configuration fields')
        transport = EventTransport(**{key: config[key] for key in fields})
        transport.validate(config['seller_account'])
        box = MeteringOutbox(config['database'], config['seller_account'], config['product_code'])
        state = PaygLicenseState(box, config['product_id'])
        import boto3
        result = SqsLifecycleWorker.from_session(boto3.Session(), state, transport).run_once()
        print(json.dumps({'persisted': result.persisted, 'duplicate': result.duplicate,
                          'delete_requested': result.delete_requested}))
        return 0
    except (MarketplaceDenied, MarketplaceUnavailable, BotoCoreError, ClientError,
            ValueError, OSError, sqlite3.Error):
        print('Event worker could not complete a verified poll; no readiness claim.', file=sys.stderr)
        return 1
    finally:
        if box is not None:
            box.close()


if __name__ == '__main__':
    raise SystemExit(main())
