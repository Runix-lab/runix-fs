"""Credential-free tests against actual AWS SDK request/response models."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import boto3
from botocore.exceptions import EndpointConnectionError
from botocore.stub import Stubber

from marketplace_adapter import (
    ContractGateway, MarketplaceDenied, MarketplaceUnavailable, Purchase,
)

SELLER = "111111111111"
BUYER = "222222222222"
PRODUCT = "test-product"
LICENSE = "arn:aws:license-manager:us-east-1:111111111111:license:test-license"
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
PURCHASE = Purchase(BUYER, LICENSE, PRODUCT, "test-agreement")
RESOLVED = {
    "CustomerAWSAccountId": BUYER, "LicenseArn": LICENSE,
    "ProductCode": PRODUCT, "Metadata": {"AgreementId": "test-agreement"},
}
PARAMS = {
    "ProductCode": PRODUCT, "MaxResults": 25,
    "Filter": {"CUSTOMER_AWS_ACCOUNT_ID": [BUYER],
               "LICENSE_ARN": [LICENSE], "DIMENSION": ["dedicated_cluster"]},
}
ENTITLEMENT = {
    "CustomerAWSAccountId": BUYER, "LicenseArn": LICENSE,
    "ProductCode": PRODUCT, "Dimension": "dedicated_cluster",
    "Value": {"IntegerValue": 1}, "ExpirationDate": NOW + timedelta(days=1),
}


class ContractAdapterTests(unittest.TestCase):
    def setUp(self):
        self.clients = {}
        self.stubs = {}
        for name in ("sts", "meteringmarketplace", "marketplace-entitlement"):
            client = boto3.client(
                name, region_name="us-east-1",
                aws_access_key_id="testing", aws_secret_access_key="testing",
            )
            stub = Stubber(client)
            stub.activate()
            self.addCleanup(stub.deactivate)
            self.clients[name] = client
            self.stubs[name] = stub
        self.stubs["sts"].add_response("get_caller_identity", {"Account": SELLER}, {})
        self.gateway = ContractGateway(
            self.clients["sts"], self.clients["meteringmarketplace"],
            self.clients["marketplace-entitlement"], SELLER, PRODUCT,
        )

    def quantity(self):
        return self.gateway.contract_quantity(PURCHASE, "dedicated_cluster", NOW)

    def test_new_registration_does_not_require_legacy_identifier(self):
        self.stubs["meteringmarketplace"].add_response(
            "resolve_customer", RESOLVED, {"RegistrationToken": "test-token"},
        )
        self.assertEqual(self.gateway.resolve_registration("test-token"), PURCHASE)

    def test_sdk_registration_preserves_slash_license_arn(self):
        arn = 'arn:aws:license-manager::111111111111:license/lic-test'
        self.stubs['meteringmarketplace'].add_response(
            'resolve_customer', {**RESOLVED, 'LicenseArn': arn},
            {'RegistrationToken': 'test-token'},
        )
        self.assertEqual(self.gateway.resolve_registration('test-token'),
                         replace(PURCHASE, license_arn=arn))

    def test_wrong_seller_never_calls_marketplace(self):
        sts = Mock()
        sts.get_caller_identity.return_value = {"Account": BUYER}
        with self.assertRaises(MarketplaceDenied):
            ContractGateway(sts, Mock(), Mock(), SELLER, PRODUCT)

    def test_factory_uses_one_session_and_supported_region(self):
        self.stubs["sts"].add_response("get_caller_identity", {"Account": SELLER}, {})
        session = Mock()
        session.client.side_effect = lambda service, **_kwargs: self.clients[service]
        gateway = ContractGateway.from_session(session, SELLER, PRODUCT)
        self.assertIs(gateway.entitlements, self.clients["marketplace-entitlement"])
        self.assertEqual(session.client.call_count, 3)
        for call in session.client.call_args_list:
            self.assertEqual(call.kwargs['region_name'], "us-east-1")
            config = call.kwargs['config']
            self.assertEqual((config.connect_timeout, config.read_timeout), (3, 5))
            self.assertEqual(config.retries['total_max_attempts'], 2)
            self.assertTrue(config.ignore_configured_endpoint_urls)

    def test_invalid_registration_input(self):
        for token in (None, "", " ", 123):
            with self.subTest(token=token), self.assertRaises(MarketplaceDenied):
                self.gateway.resolve_registration(token)

    def test_invalid_expired_and_replayed_registration(self):
        for code in ("InvalidTokenException", "ExpiredTokenException"):
            self.stubs["meteringmarketplace"].add_client_error(
                "resolve_customer", service_error_code=code,
                service_message="sensitive-token-must-not-leak",
                expected_params={"RegistrationToken": "test-token"},
            )
            with self.assertRaises(MarketplaceDenied) as raised:
                self.gateway.resolve_registration("test-token")
            self.assertNotIn("sensitive", str(raised.exception))

    def test_registration_response_identity_is_required(self):
        for key in ("CustomerAWSAccountId", "LicenseArn", "ProductCode", "Metadata"):
            response = dict(RESOLVED)
            response.pop(key)
            self.stubs["meteringmarketplace"].add_response(
                "resolve_customer", response, {"RegistrationToken": "test-token"},
            )
            with self.subTest(key=key), self.assertRaises(MarketplaceDenied):
                self.gateway.resolve_registration("test-token")

    def test_wrong_product_is_denied(self):
        response = {**RESOLVED, "ProductCode": "another-product"}
        self.stubs["meteringmarketplace"].add_response(
            "resolve_customer", response, {"RegistrationToken": "test-token"},
        )
        with self.assertRaises(MarketplaceDenied):
            self.gateway.resolve_registration("test-token")

    def test_malformed_concurrent_agreement_identifiers_are_denied(self):
        for mutation in (
            {"Metadata": {}}, {"CustomerAWSAccountId": "not-an-account"},
            {"LicenseArn": "https://example.invalid"},
        ):
            self.stubs["meteringmarketplace"].add_response(
                "resolve_customer", {**RESOLVED, **mutation}, {"RegistrationToken": "test-token"},
            )
            with self.subTest(mutation=mutation), self.assertRaises(MarketplaceDenied):
                self.gateway.resolve_registration("test-token")

    def test_empty_page_followed_by_active_entitlement(self):
        stub = self.stubs["marketplace-entitlement"]
        stub.add_response("get_entitlements", {"Entitlements": [], "NextToken": "next"}, PARAMS)
        stub.add_response("get_entitlements", {"Entitlements": [ENTITLEMENT]}, {**PARAMS, "NextToken": "next"})
        self.assertEqual(self.quantity(), 1)
        stub.assert_no_pending_responses()

    def test_no_purchase_and_no_entitlements_are_denied(self):
        with self.assertRaises(MarketplaceDenied):
            self.gateway.contract_quantity(None, "dedicated_cluster", NOW)
        self.stubs["marketplace-entitlement"].add_response("get_entitlements", {}, PARAMS)
        with self.assertRaises(MarketplaceDenied):
            self.quantity()

    def test_untrusted_purchase_cannot_select_another_product(self):
        with self.assertRaises(MarketplaceDenied):
            self.gateway.contract_quantity(replace(PURCHASE, product_code="other"), "dedicated_cluster", NOW)

    def test_stale_expired_ambiguous_and_cross_license_entitlements(self):
        mutations = [
            {"ExpirationDate": NOW}, {"ExpirationDate": NOW - timedelta(seconds=1)},
            {"Value": {"IntegerValue": 0}}, {"Value": {"DoubleValue": 1.5}},
            {"Value": {"IntegerValue": 1, "BooleanValue": True}},
            {"CustomerAWSAccountId": SELLER}, {"LicenseArn": LICENSE + "-other"},
            {"ProductCode": "other"}, {"Dimension": "other"},
        ]
        for mutation in mutations:
            self.stubs["marketplace-entitlement"].add_response(
                "get_entitlements", {"Entitlements": [{**ENTITLEMENT, **mutation}]}, PARAMS,
            )
            with self.subTest(mutation=mutation), self.assertRaises(MarketplaceDenied):
                self.quantity()

    def test_duplicate_grants_are_never_added(self):
        self.stubs["marketplace-entitlement"].add_response(
            "get_entitlements", {"Entitlements": [ENTITLEMENT, ENTITLEMENT]}, PARAMS,
        )
        with self.assertRaises(MarketplaceDenied):
            self.quantity()

    def test_repeating_page_token_fails_closed(self):
        stub = self.stubs["marketplace-entitlement"]
        stub.add_response("get_entitlements", {"NextToken": "loop"}, PARAMS)
        stub.add_response("get_entitlements", {"NextToken": "loop"}, {**PARAMS, "NextToken": "loop"})
        with self.assertRaises(MarketplaceUnavailable):
            self.quantity()

    def test_unbounded_distinct_pages_fail_closed(self):
        self.gateway.entitlements = Mock()
        self.gateway.entitlements.get_entitlements.side_effect = [
            {"NextToken": f"page-{index}"} for index in range(100)
        ]
        with self.assertRaises(MarketplaceUnavailable):
            self.quantity()

    def test_duplicate_grants_across_pages_are_denied(self):
        stub = self.stubs["marketplace-entitlement"]
        stub.add_response("get_entitlements", {"Entitlements": [ENTITLEMENT], "NextToken": "next"}, PARAMS)
        stub.add_response("get_entitlements", {"Entitlements": [ENTITLEMENT]}, {**PARAMS, "NextToken": "next"})
        with self.assertRaises(MarketplaceDenied):
            self.quantity()

    def test_aws_outage_and_throttling_do_not_grant_access(self):
        self.stubs["marketplace-entitlement"].add_client_error(
            "get_entitlements", service_error_code="ThrottlingException", expected_params=PARAMS,
        )
        with self.assertRaises(MarketplaceUnavailable):
            self.quantity()
        self.gateway.entitlements = Mock()
        self.gateway.entitlements.get_entitlements.side_effect = EndpointConnectionError(endpoint_url="https://example.invalid")
        with self.assertRaises(MarketplaceUnavailable):
            self.quantity()

    def test_dimension_and_time_validation(self):
        for dimension, instant in (("", NOW), ("bad dimension", NOW), ("dedicated_cluster", NOW.replace(tzinfo=None))):
            with self.subTest(dimension=dimension), self.assertRaises(ValueError):
                self.gateway.contract_quantity(PURCHASE, dimension, instant)

    def test_concurrent_reads_do_not_accumulate_capacity(self):
        self.gateway.entitlements = Mock()
        self.gateway.entitlements.get_entitlements.return_value = {"Entitlements": [ENTITLEMENT]}
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: self.quantity(), range(8)))
        self.assertEqual(results, [1] * 8)
        self.assertEqual(PURCHASE.account_id, BUYER)


if __name__ == "__main__":
    unittest.main()
