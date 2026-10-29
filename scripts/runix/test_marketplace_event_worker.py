"""Actual SDK models and durable reducers; no live queue or claimed AWS origin."""
import copy
import contextlib
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

import boto3
from botocore.exceptions import NoCredentialsError
from botocore.stub import Stubber

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable
from marketplace_event_worker import (ATTRIBUTES, EventTransport, SqsLifecycleWorker,
                                      main, queue_policy, strict_json)
from marketplace_lifecycle import DEPROVISIONED
from marketplace_metering import MeteringOutbox
from marketplace_payg_license import PaygLicenseState
from test_marketplace_payg_license import SELLER, PRODUCT, PRODUCT_ID, NOW, PURCHASE, event

TRANSPORT = EventTransport(
    f'https://sqs.us-east-1.amazonaws.com/{SELLER}/runix-events-test',
    f'arn:aws:sqs:us-east-1:{SELLER}:runix-events-test',
    f'arn:aws:events:us-east-1:{SELLER}:rule/runix-events-test',
    f'arn:aws:iam::{SELLER}:role/RunixEventsTest',
    f'arn:aws:sqs:us-east-1:{SELLER}:runix-processing-test',
    f'arn:aws:sqs:us-east-1:{SELLER}:runix-delivery-test',
)
ROLE = f'arn:aws:sts::{SELLER}:assumed-role/RunixEventsTest/test-session'
RECEIVE = dict(QueueUrl=TRANSPORT.queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=10,
               VisibilityTimeout=60, MessageSystemAttributeNames=['ApproximateReceiveCount', 'SentTimestamp'])


def attributes(arn):
    result = {'QueueArn': arn, 'MessageRetentionPeriod': '345600' if arn == TRANSPORT.queue_arn else '1209600',
              'SqsManagedSseEnabled': 'true', 'VisibilityTimeout': '60'}
    if arn in {TRANSPORT.queue_arn, TRANSPORT.delivery_dlq_arn}:
        result['Policy'] = json.dumps(queue_policy(arn, TRANSPORT.rule_arn, SELLER))
    if arn == TRANSPORT.queue_arn:
        result['RedrivePolicy'] = json.dumps({'deadLetterTargetArn': TRANSPORT.processing_dlq_arn, 'maxReceiveCount': 3})
    if arn == TRANSPORT.processing_dlq_arn:
        result['RedriveAllowPolicy'] = json.dumps({'redrivePermission': 'byQueue', 'sourceQueueArns': [TRANSPORT.queue_arn]})
    return result


def message(value=None, body=None, handle='synthetic-receipt'):
    text = body if body is not None else json.dumps(value or event())
    return {'MessageId': 'synthetic-message', 'ReceiptHandle': handle, 'Body': text,
            'MD5OfBody': hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()}


class EventWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.box = MeteringOutbox(str(Path(self.temp.name) / 'events.sqlite'), SELLER, PRODUCT)
        self.addCleanup(self.box.close)
        self.state = PaygLicenseState(self.box, PRODUCT_ID)
        self.clients, self.stubs = {}, {}
        for service in ('sts', 'sqs', 'events'):
            client = boto3.client(service, region_name='us-east-1',
                                  aws_access_key_id='testing', aws_secret_access_key='testing')
            stub = Stubber(client)
            stub.activate()
            self.addCleanup(stub.deactivate)
            self.clients[service], self.stubs[service] = client, stub
        self.worker = SqsLifecycleWorker(self.clients['sts'], self.clients['sqs'], self.clients['events'], self.state, TRANSPORT)

    def preflight(self, *, identity=None, main=None, processing=None, delivery=None, rule=None, targets=None):
        self.stubs['sts'].add_response('get_caller_identity', identity or {'Account': SELLER, 'Arn': ROLE}, {})
        for arn, override in ((TRANSPORT.queue_arn, main), (TRANSPORT.processing_dlq_arn, processing),
                              (TRANSPORT.delivery_dlq_arn, delivery)):
            self.stubs['sqs'].add_response('get_queue_attributes', {'Attributes': {**attributes(arn), **(override or {})}},
                {'QueueUrl': TRANSPORT.url(arn), 'AttributeNames': ATTRIBUTES})
        base_rule = {'Name': 'runix-events-test', 'Arn': TRANSPORT.rule_arn, 'State': 'ENABLED', 'EventBusName': 'default',
                     'EventPattern': json.dumps({'source': ['aws.agreement-marketplace'], 'account': [SELLER],
                         'region': ['us-east-1'], '$or': [
                             {'detail-type': ['License Deprovisioned - Manufacturer', 'License Updated - Manufacturer'],
                              'detail': {'product': {'id': [PRODUCT_ID], 'code': [PRODUCT]}}},
                             {'detail-type': ['Purchase Agreement Ended - Manufacturer', 'Purchase Agreement Ended - Proposer'],
                              'detail': {'product': {'id': [PRODUCT_ID, {'exists': False}]}}},
                         ]})}
        self.stubs['events'].add_response('describe_rule', {**base_rule, **(rule or {})},
                                         {'Name': 'runix-events-test', 'EventBusName': 'default'})
        base_target = {'Id': 'lifecycle', 'Arn': TRANSPORT.queue_arn,
                       'DeadLetterConfig': {'Arn': TRANSPORT.delivery_dlq_arn},
                       'RetryPolicy': {'MaximumRetryAttempts': 185, 'MaximumEventAgeInSeconds': 86400}}
        self.stubs['events'].add_response('list_targets_by_rule', targets if targets is not None else {'Targets': [base_target]},
                                         {'Rule': 'runix-events-test', 'EventBusName': 'default', 'Limit': 100})

    def poll(self, msg, *, delete_error=False, second=None):
        self.preflight()
        self.stubs['sqs'].add_response('receive_message', {'Messages': [msg]} if msg is not None else {}, RECEIVE)
        if msg is not None:
            self.preflight(**(second or {}))
            if delete_error:
                self.stubs['sqs'].add_client_error('delete_message', service_error_code='RequestThrottled',
                    service_message='sensitive-receipt-must-not-leak',
                    expected_params={'QueueUrl': TRANSPORT.queue_url, 'ReceiptHandle': msg['ReceiptHandle']})
            else:
                self.stubs['sqs'].add_response('delete_message', {},
                    {'QueueUrl': TRANSPORT.queue_url, 'ReceiptHandle': msg['ReceiptHandle']})

    def run_one(self):
        return self.worker.run_once(clock=lambda: NOW)

    def test_real_sdk_route_commits_before_deleting(self):
        self.poll(message())
        delete = self.clients['sqs'].delete_message
        def committed(**parameters):
            self.assertFalse(self.box.db.in_transaction)
            self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 1)
            return delete(**parameters)
        with patch.object(self.clients['sqs'], 'delete_message', side_effect=committed):
            result = self.run_one()
        self.assertTrue(result.persisted and result.delete_requested)
        self.assertFalse(result.duplicate)
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()

    def test_empty_poll_neither_mutates_nor_deletes(self):
        self.poll(None)
        self.assertFalse(self.run_one().persisted)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()

    def test_string_receive_count_uses_same_narrow_profile(self):
        self.preflight(main={'RedrivePolicy': json.dumps({
            'deadLetterTargetArn': TRANSPORT.processing_dlq_arn, 'maxReceiveCount': '3'})})
        self.worker.preflight()
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()

    def test_delete_failure_is_safe_for_same_event_redelivery_with_new_handle(self):
        value = event()
        self.poll(message(value), delete_error=True)
        with self.assertRaises(MarketplaceUnavailable) as caught:
            self.run_one()
        self.assertNotIn('sensitive', str(caught.exception))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 1)
        self.poll(message(value, handle='different-receipt'))
        self.assertTrue(self.run_one().duplicate)
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 1)
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()

    def test_negative_event_reaches_durable_stop_guard(self):
        self.poll(message(event(kind=DEPROVISIONED)))
        self.assertTrue(self.run_one().persisted)
        self.assertIsNotNone(self.box.stop_info(PURCHASE.license_arn))

    def test_archived_positive_and_negative_replays_do_not_resurrect(self):
        positive, negative = event(), event(kind=DEPROVISIONED)
        for value in (positive, negative):
            self.poll(message(value))
            self.assertTrue(self.run_one().persisted)
        for value in (positive, negative):
            self.poll(message({**value, 'replay-name': 'synthetic-recovery-replay'}))
            self.assertTrue(self.run_one().duplicate)
        self.assertIsNotNone(self.box.stop_info(PURCHASE.license_arn))
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 2)
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()

    def test_replay_tag_does_not_hide_changed_purchase_identity(self):
        value = event()
        self.poll(message(value))
        self.run_one()
        altered = copy.deepcopy(value)
        altered['replay-name'] = 'synthetic-replay'
        altered['detail']['license']['arn'] += 'other'
        self.preflight()
        self.stubs['sqs'].add_response('receive_message', {'Messages': [message(altered)]}, RECEIVE)
        self.preflight()
        with self.assertRaises(ValueError):
            self.run_one()
        self.stubs['sqs'].assert_no_pending_responses()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM licenses').fetchone()[0], 1)

    def test_malformed_replay_metadata_is_not_acknowledged(self):
        value = {**event(), 'replay-name': 'invalid?name'}
        self.preflight()
        self.stubs['sqs'].add_response('receive_message', {'Messages': [message(value)]}, RECEIVE)
        self.preflight()
        with self.assertRaises(ValueError):
            self.run_one()
        self.stubs['sqs'].assert_no_pending_responses()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)

    def test_legacy_replay_digest_is_never_silently_rewritten(self):
        value = {**event(kind=DEPROVISIONED), 'replay-name': 'legacy-replay'}
        self.state.negative.apply(value, NOW)
        legacy = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        self.box.db.execute('UPDATE lifecycle_events SET digest=? WHERE id=?', (legacy, value['id']))
        with self.assertRaises(ValueError):
            self.state.negative.apply(value, NOW)
        self.assertEqual(self.box.db.execute('SELECT digest FROM lifecycle_events').fetchone()[0], legacy)
        self.assertIsNotNone(self.box.stop_info(PURCHASE.license_arn))

    def test_root_wrong_role_and_account_refuse_before_receive(self):
        for identity in ({'Account': SELLER, 'Arn': f'arn:aws:iam::{SELLER}:root'},
                         {'Account': SELLER, 'Arn': ROLE.replace('/RunixEventsTest/', '/OtherRole/')},
                         {'Account': '111111111111', 'Arn': ROLE}):
            self.stubs['sts'].add_response('get_caller_identity', identity, {})
            with self.subTest(identity=identity), self.assertRaises(MarketplaceDenied):
                self.run_one()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)

    def test_bad_configuration_rejected_before_any_aws_call(self):
        for field, value in (('queue_url', 'https://example.invalid/queue'),
                             ('queue_arn', TRANSPORT.queue_arn.replace(SELLER, '111111111111')),
                             ('processing_dlq_arn', TRANSPORT.queue_arn),
                             ('rule_arn', TRANSPORT.rule_arn.replace(':rule/', ':rule/custom/')),
                             ('consumer_role_arn', f'arn:aws:iam::{SELLER}:root')):
            with self.subTest(field=field), self.assertRaises(ValueError):
                SqsLifecycleWorker(*self.clients.values(), self.state, replace(TRANSPORT, **{field: value}))

    def test_send_policy_without_explicit_foreign_source_deny_is_refused(self):
        policy = queue_policy(TRANSPORT.queue_arn, TRANSPORT.rule_arn, SELLER)
        policy['Statement'].pop()
        self.preflight(main={'Policy': json.dumps(policy)})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_wildcard_sender_policy_is_refused(self):
        policy = queue_policy(TRANSPORT.queue_arn, TRANSPORT.rule_arn, SELLER)
        policy['Statement'][0]['Principal'] = '*'
        self.preflight(main={'Policy': json.dumps(policy)})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_unencrypted_queue_is_refused(self):
        self.preflight(main={'SqsManagedSseEnabled': 'false'})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_substituted_queue_is_refused(self):
        self.preflight(main={'QueueArn': TRANSPORT.delivery_dlq_arn})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_wrong_processing_dead_letter_target_is_refused(self):
        self.preflight(main={'RedrivePolicy': json.dumps({
            'deadLetterTargetArn': TRANSPORT.delivery_dlq_arn, 'maxReceiveCount': 3})})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_processing_dead_letter_foreign_source_is_refused(self):
        self.preflight(processing={'RedriveAllowPolicy': json.dumps({'redrivePermission': 'allowAll'})})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_delivery_dead_letter_policy_is_verified(self):
        self.preflight(delivery={'Policy': '{}'})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_rule_disabled_is_refused(self):
        self.preflight(rule={'State': 'DISABLED'})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_enabled_rule_with_wrong_source_is_refused(self):
        self.preflight(rule={'EventPattern': json.dumps({'source': ['custom.forged']})})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_transformed_target_cannot_forge_aws_event_body(self):
        for transform in ({'Input': json.dumps(event())}, {'InputPath': '$.detail'},
                          {'InputTransformer': {'InputPathsMap': {'payload': '$.detail'}, 'InputTemplate': '<payload>'}}):
            target = {'Id': 'lifecycle', 'Arn': TRANSPORT.queue_arn,
                      'DeadLetterConfig': {'Arn': TRANSPORT.delivery_dlq_arn},
                      'RetryPolicy': {'MaximumRetryAttempts': 185, 'MaximumEventAgeInSeconds': 86400}, **transform}
            self.preflight(targets={'Targets': [target]})
            with self.subTest(transform=next(iter(transform))), self.assertRaises(MarketplaceDenied):
                self.run_one()
        for stub in self.stubs.values():
            stub.assert_no_pending_responses()

    def test_unknown_additional_or_paginated_targets_are_refused(self):
        self.preflight(targets={'Targets': [{'Id': 'lifecycle', 'Arn': TRANSPORT.queue_arn}],
                                'NextToken': 'unknown-next-page'})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()

    def test_config_change_during_poll_prevents_any_database_mutation(self):
        self.poll(message(), second={'main': {'Policy': '{}'}})
        with self.assertRaises(MarketplaceDenied):
            self.run_one()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)

    def test_corrupt_body_checksum_is_not_acknowledged(self):
        self.preflight()
        msg = {**message(), 'MD5OfBody': '0' * 32}
        self.stubs['sqs'].add_response('receive_message', {'Messages': [msg]}, RECEIVE)
        self.preflight()
        with self.assertRaises(ValueError):
            self.run_one()
        self.stubs['sqs'].assert_no_pending_responses()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)

    def test_missing_receipt_or_message_identity_does_not_mutate(self):
        for key in ('ReceiptHandle', 'MessageId'):
            msg = message()
            del msg[key]
            self.preflight()
            self.stubs['sqs'].add_response('receive_message', {'Messages': [msg]}, RECEIVE)
            self.preflight()
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_one()
        self.assertEqual(self.box.db.execute('SELECT COUNT(*) FROM lifecycle_events').fetchone()[0], 0)
        self.stubs['sqs'].assert_no_pending_responses()

    def test_duplicate_json_keys_are_not_acknowledged(self):
        self.preflight()
        msg = message(body='{"source":"aws.agreement-marketplace","source":"forged"}')
        self.stubs['sqs'].add_response('receive_message', {'Messages': [msg]}, RECEIVE)
        self.preflight()
        with self.assertRaises(ValueError):
            self.run_one()
        self.stubs['sqs'].assert_no_pending_responses()

    def test_foreign_event_is_not_acknowledged(self):
        self.preflight()
        value = event()
        value['detail']['product']['code'] = 'other'
        self.stubs['sqs'].add_response('receive_message', {'Messages': [message(value)]}, RECEIVE)
        self.preflight()
        with self.assertRaises(MarketplaceDenied):
            self.run_one()
        self.stubs['sqs'].assert_no_pending_responses()

    def test_database_failure_does_not_delete(self):
        self.preflight()
        self.stubs['sqs'].add_response('receive_message', {'Messages': [message()]}, RECEIVE)
        self.preflight()
        with patch.object(self.state, 'record_update', side_effect=sqlite3.OperationalError('synthetic')), \
                self.assertRaises(sqlite3.OperationalError):
            self.run_one()
        self.stubs['sqs'].assert_no_pending_responses()

    def test_transport_error_is_sanitized_and_never_polls(self):
        self.stubs['sts'].add_client_error('get_caller_identity', service_error_code='AccessDenied',
                                          service_message='private-value', expected_params={})
        with self.assertRaises(MarketplaceUnavailable) as caught:
            self.run_one()
        self.assertNotIn('private', str(caught.exception))

    def test_factory_pins_clients_region_endpoints_and_long_poll_timeout(self):
        session = Mock()
        session.client.side_effect = [self.clients[name] for name in ('sts', 'sqs', 'events')]
        SqsLifecycleWorker.from_session(session, self.state, TRANSPORT)
        for call in session.client.call_args_list:
            self.assertEqual(call.kwargs['region_name'], 'us-east-1')
            self.assertGreater(call.kwargs['config'].read_timeout, RECEIVE['WaitTimeSeconds'])
            self.assertTrue(call.kwargs['config'].ignore_configured_endpoint_urls)
            self.assertEqual(call.kwargs['config'].retries['total_max_attempts'], 2)

    def test_strict_json_rejects_nonfinite_duplicate_and_oversized_data(self):
        for value in ('{"x":NaN}', '{"x":1,"x":2}', ' ' * 65537, None):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ValueError):
                strict_json(value)

    def test_cli_missing_credentials_is_sanitized_without_running_worker(self):
        config = {**TRANSPORT.__dict__, 'database': str(Path(self.temp.name) / 'cli.sqlite'),
                  'seller_account': SELLER, 'product_code': PRODUCT, 'product_id': PRODUCT_ID}
        path = Path(self.temp.name) / 'worker.json'
        path.write_text(json.dumps(config))
        with patch('sys.argv', ['worker', '--config', str(path)]), patch('boto3.Session', return_value=Mock()), \
                patch.object(SqsLifecycleWorker, 'from_session', side_effect=NoCredentialsError()), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(), 1)
        self.assertEqual(error.getvalue(), 'Event worker could not complete a verified poll; no readiness claim.\n')

    def test_cli_rejects_credential_fields_without_echoing_values(self):
        path = Path(self.temp.name) / 'bad-config.json'
        path.write_text(json.dumps({'aws_secret_access_key': 'synthetic-do-not-echo'}))
        with patch('sys.argv', ['worker', '--config', str(path)]), \
                contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main(), 1)
        self.assertNotIn('synthetic-do-not-echo', error.getvalue())


if __name__ == '__main__':
    unittest.main()
