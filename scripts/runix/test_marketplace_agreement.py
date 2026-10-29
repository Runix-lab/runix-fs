"""Read-only agreement checks with actual botocore response validation."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import boto3
from botocore.stub import Stubber

from marketplace_adapter import MarketplaceDenied, MarketplaceUnavailable, Purchase, validate_purchase
from marketplace_agreement import AgreementReader

SELLER, BUYER = '111111111111', '222222222222'
PRODUCT, PRODUCT_ID = 'test-product', 'prod-test'
NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)
PURCHASE = Purchase(BUYER, 'arn:aws:license-manager::111111111111:license/lic-test', PRODUCT, 'agmt-test')
RESPONSE = {
    'agreementId': PURCHASE.agreement_id, 'agreementType': 'PurchaseAgreement',
    'acceptor': {'accountId': BUYER}, 'proposer': {'accountId': SELLER},
    'proposalSummary': {'resources': [{'id': PRODUCT_ID, 'type': 'SaaSProduct'}]},
    'startTime': NOW - timedelta(days=1), 'status': 'ACTIVE',
}


class AgreementTests(unittest.TestCase):
    def setUp(self):
        self.sts = Mock()
        self.sts.get_caller_identity.return_value = {'Account': SELLER}
        self.client = boto3.client('marketplace-agreement', region_name='us-east-1',
                                  aws_access_key_id='testing', aws_secret_access_key='testing')
        self.stub = Stubber(self.client)
        self.stub.activate()
        self.addCleanup(self.stub.deactivate)
        self.reader = AgreementReader(self.sts, self.client, SELLER, PRODUCT, PRODUCT_ID)

    def response(self, **changes):
        self.stub.add_response('describe_agreement', {**RESPONSE, **changes},
                               {'agreementId': PURCHASE.agreement_id})

    def test_fresh_minimal_snapshot_no_end_date_and_replay(self):
        for _ in range(2):
            self.response(estimatedCharges={'currencyCode': 'USD', 'agreementValue': '999'})
            result = self.reader.describe(PURCHASE, NOW)
            self.assertEqual(result.status, 'ACTIVE')
            self.assertEqual(result.observed_at, NOW)
            self.assertIsNone(result.ends_at)
            self.assertEqual(set(asdict(result)), {'agreement_id', 'status', 'starts_at', 'ends_at', 'observed_at'})
        self.assertEqual(self.sts.get_caller_identity.call_count, 2)
        self.stub.assert_no_pending_responses()

    def test_every_known_status_is_evidence_and_not_activation(self):
        for status in ('ACTIVE', 'ARCHIVED', 'CANCELLED', 'EXPIRED', 'RENEWED', 'REPLACED',
                       'ROLLED_BACK', 'SUPERSEDED', 'TERMINATED'):
            self.response(status=status)
            result = self.reader.describe(PURCHASE, NOW)
            self.assertEqual(result.status, status)
            self.assertFalse(hasattr(result, 'active_license'))

    def test_wrong_seller_and_rotated_session_never_reads_agreement(self):
        self.response()
        self.reader.describe(PURCHASE, NOW)
        self.sts.get_caller_identity.return_value = {'Account': BUYER}
        with self.assertRaises(MarketplaceDenied):
            self.reader.describe(PURCHASE, NOW)
        self.stub.assert_no_pending_responses()

    def test_identity_and_resource_substitution_are_denied(self):
        for mutation in (
            {'agreementId': 'other'}, {'agreementType': 'VendorInsightsAgreement'},
            {'acceptor': {'accountId': SELLER}}, {'proposer': {'accountId': BUYER}},
            {'proposalSummary': {}},
            {'proposalSummary': {'resources': [{'id': 'prod-other', 'type': 'SaaSProduct'}]}},
            {'proposalSummary': {'resources': [{'id': PRODUCT_ID, 'type': 'AmiProduct'}]}},
            {'proposalSummary': {'resources': RESPONSE['proposalSummary']['resources'] * 2}},
            {'status': 'UNKNOWN'},
        ):
            with self.subTest(mutation=mutation):
                self.response(**mutation)
                with self.assertRaises(MarketplaceDenied):
                    self.reader.describe(PURCHASE, NOW)

    def test_missing_required_evidence_is_denied_even_when_sdk_allows_it(self):
        for key in RESPONSE:
            response = dict(RESPONSE)
            del response[key]
            self.stub.add_response('describe_agreement', response, {'agreementId': PURCHASE.agreement_id})
            with self.subTest(key=key), self.assertRaises(MarketplaceDenied):
                self.reader.describe(PURCHASE, NOW)

    def test_invalid_local_parameters_do_not_call_aws(self):
        for purchase in (None, replace(PURCHASE, product_code='other'),
                         replace(PURCHASE, agreement_id='bad?query'),
                         replace(PURCHASE, agreement_id='a' * 65)):
            with self.assertRaises(MarketplaceDenied):
                self.reader.describe(purchase, NOW)
        for now in (None, NOW.replace(tzinfo=None), '2026-10-29'):
            with self.assertRaises(ValueError):
                self.reader.describe(PURCHASE, now)
        self.sts.get_caller_identity.assert_not_called()

    def test_future_start_or_elapsed_end_never_rewritten(self):
        for start, end in ((NOW + timedelta(days=1), None),
                           (NOW - timedelta(days=2), NOW - timedelta(days=1))):
            self.response(startTime=start, **({'endTime': end} if end else {}))
            result = self.reader.describe(PURCHASE, NOW)
            self.assertEqual((result.starts_at, result.ends_at), (start, end))

    def test_invalid_and_naive_dates_are_denied(self):
        for mutation in ({'endTime': RESPONSE['startTime']},
                         {'endTime': NOW - timedelta(days=2)},
                         {'startTime': NOW.replace(tzinfo=None)},
                         {'endTime': NOW.replace(tzinfo=None)}):
            self.response(**mutation)
            with self.assertRaises(MarketplaceDenied):
                self.reader.describe(PURCHASE, NOW)

    def test_aws_errors_are_unavailable_never_eligibility_and_never_leak(self):
        for code in ('AccessDeniedException', 'ResourceNotFoundException',
                     'ThrottlingException', 'InternalServerException'):
            self.stub.add_client_error('describe_agreement', service_error_code=code,
                                       service_message='private response must not leak',
                                       expected_params={'agreementId': PURCHASE.agreement_id})
            with self.assertRaises(MarketplaceUnavailable) as raised:
                self.reader.describe(PURCHASE, NOW)
            self.assertNotIn('private', str(raised.exception))

    def test_factory_pins_region_and_transport_limits(self):
        session = Mock()
        session.client.side_effect = [self.sts, self.client]
        AgreementReader.from_session(session, SELLER, PRODUCT, PRODUCT_ID)
        self.assertEqual([c.args[0] for c in session.client.call_args_list], ['sts', 'marketplace-agreement'])
        for call in session.client.call_args_list:
            self.assertEqual(call.kwargs['region_name'], 'us-east-1')
            self.assertTrue(call.kwargs['config'].ignore_configured_endpoint_urls)
            self.assertEqual(call.kwargs['config'].retries['total_max_attempts'], 2)

    def test_bad_config_denied_before_identity_reads(self):
        for args in ((BUYER + '0', PRODUCT, PRODUCT_ID), (SELLER, '', PRODUCT_ID),
                     (SELLER, PRODUCT, 'invalid')):
            with self.assertRaises(ValueError):
                AgreementReader(self.sts, self.client, *args)
        self.sts.get_caller_identity.assert_not_called()

    def test_parallel_reads_have_independent_snapshots_and_no_mutations(self):
        client = Mock()
        client.describe_agreement.return_value = RESPONSE
        reader = AgreementReader(self.sts, client, SELLER, PRODUCT, PRODUCT_ID)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: reader.describe(PURCHASE, NOW), range(8)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(client.describe_agreement.call_count, 8)

    def test_license_arn_colon_and_slash_formats_remain_exact_identities(self):
        for arn in ('arn:aws:license-manager::111111111111:license/lic-test',
                    'arn:aws:license-manager:us-east-1:111111111111:license:test-license'):
            validate_purchase(replace(PURCHASE, license_arn=arn), PRODUCT)
        for arn in (PURCHASE.license_arn + '/extra', PURCHASE.license_arn + '?token=x',
                    PURCHASE.license_arn + '\n', PURCHASE.license_arn.replace('arn:aws:', 'arn:aws-cn:'),
                    PURCHASE.license_arn.replace(':license/', ':grant/')):
            with self.assertRaises(MarketplaceDenied):
                validate_purchase(replace(PURCHASE, license_arn=arn), PRODUCT)


if __name__ == '__main__':
    unittest.main()
