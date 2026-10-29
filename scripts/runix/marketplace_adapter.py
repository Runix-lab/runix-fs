"""AWS registration and optional Contract adapter; no HTTP/provisioning side effects."""

import re
from dataclasses import dataclass
from datetime import datetime

from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class MarketplaceDenied(Exception):
    pass


class MarketplaceUnavailable(Exception):
    pass


@dataclass(frozen=True)
class Purchase:
    account_id: str
    license_arn: str
    product_code: str
    agreement_id: str


def validate_purchase(purchase, expected_product):
    if (
        not isinstance(purchase, Purchase)
        or not isinstance(purchase.account_id, str)
        or not re.fullmatch(r"[0-9]{12}", purchase.account_id)
        or not isinstance(purchase.license_arn, str)
        or not re.fullmatch(
            r"arn:aws:license-manager:[a-z0-9-]*:[0-9]{12}:license[:/][A-Za-z0-9-]+",
            purchase.license_arn,
        )
        or purchase.product_code != expected_product
        or not isinstance(purchase.agreement_id, str)
        or not purchase.agreement_id.strip()
    ):
        raise MarketplaceDenied("Invalid Marketplace purchase identity")


class RegistrationGateway:
    @staticmethod
    def _client(session, service):
        return session.client(service, region_name="us-east-1", config=Config(
            connect_timeout=3, read_timeout=5,
            retries={"mode": "standard", "total_max_attempts": 2},
            ignore_configured_endpoint_urls=True,
        ))

    @classmethod
    def from_session(cls, session, seller_account, product_code):
        return cls(
            cls._client(session, "sts"),
            cls._client(session, "meteringmarketplace"),
            seller_account,
            product_code,
        )

    def __init__(self, sts, metering, seller_account, product_code):
        if (not isinstance(seller_account, str)
                or not re.fullmatch(r"[0-9]{12}", seller_account)
                or not isinstance(product_code, str) or not product_code.strip()):
            raise ValueError("Seller account and product code are required")
        identity = self._call(sts.get_caller_identity)
        if identity.get("Account") != seller_account:
            raise MarketplaceDenied("AWS caller is not the configured seller")
        self.metering = metering
        self.product_code = product_code
        self.seller_account = seller_account

    @staticmethod
    def _call(operation, **parameters):
        try:
            return operation(**parameters)
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code")
            if code in {"InvalidTokenException", "ExpiredTokenException"}:
                raise MarketplaceDenied("Invalid or expired registration") from None
            raise MarketplaceUnavailable("AWS verification failed") from None
        except BotoCoreError:
            raise MarketplaceUnavailable("AWS verification unavailable") from None

    def resolve_registration(self, token):
        if not isinstance(token, str) or not token.strip():
            raise MarketplaceDenied("Registration token required")
        result = self._call(self.metering.resolve_customer, RegistrationToken=token)
        metadata = result.get("Metadata")
        if not isinstance(metadata, dict):
            raise MarketplaceDenied("Marketplace agreement metadata missing")
        purchase = Purchase(
            result.get("CustomerAWSAccountId"),
            result.get("LicenseArn"),
            result.get("ProductCode"),
            metadata.get("AgreementId"),
        )
        validate_purchase(purchase, self.product_code)
        return purchase


class ContractGateway(RegistrationGateway):
    @classmethod
    def from_session(cls, session, seller_account, product_code):
        return cls(
            cls._client(session, "sts"),
            cls._client(session, "meteringmarketplace"),
            cls._client(session, "marketplace-entitlement"),
            seller_account,
            product_code,
        )

    def __init__(self, sts, metering, entitlements, seller_account, product_code):
        super().__init__(sts, metering, seller_account, product_code)
        self.entitlements = entitlements

    def contract_quantity(self, purchase, dimension, now):
        validate_purchase(purchase, self.product_code)
        if not isinstance(dimension, str) or not re.fullmatch(r"[A-Za-z0-9_]+", dimension):
            raise ValueError("A dimension API name is required")
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("An aware verification time is required")
        parameters = {
            "ProductCode": self.product_code,
            "Filter": {
                "CUSTOMER_AWS_ACCOUNT_ID": [purchase.account_id],
                "LICENSE_ARN": [purchase.license_arn],
                "DIMENSION": [dimension],
            },
            "MaxResults": 25,
        }
        seen_tokens = set()
        quantity = None
        for _page_number in range(100):
            page = self._call(self.entitlements.get_entitlements, **parameters)
            for entitlement in page.get("Entitlements", []):
                if any(
                    entitlement.get(key) != expected
                    for key, expected in {
                        "ProductCode": self.product_code,
                        "CustomerAWSAccountId": purchase.account_id,
                        "LicenseArn": purchase.license_arn,
                        "Dimension": dimension,
                    }.items()
                ):
                    raise MarketplaceDenied("Entitlement identity mismatch")
                value = entitlement.get("Value", {})
                amount = value.get("IntegerValue")
                expiry = entitlement.get("ExpirationDate")
                if (
                    set(value) != {"IntegerValue"}
                    or type(amount) is not int
                    or amount <= 0
                    or not isinstance(expiry, datetime)
                    or expiry.tzinfo is None
                    or expiry.utcoffset() is None
                    or expiry <= now
                    or quantity is not None
                ):
                    raise MarketplaceDenied("Invalid, expired or ambiguous entitlement")
                quantity = amount
            next_token = page.get("NextToken")
            if not next_token:
                if quantity is None:
                    raise MarketplaceDenied("No active Contract entitlement")
                return quantity
            if next_token in seen_tokens:
                raise MarketplaceUnavailable("Entitlement pagination did not advance")
            seen_tokens.add(next_token)
            parameters["NextToken"] = next_token
        raise MarketplaceUnavailable("Entitlement pagination exceeded safety limit")
