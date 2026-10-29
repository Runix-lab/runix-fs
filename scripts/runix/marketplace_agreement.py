"""Read-only seller agreement evidence; never a license or provisioning grant."""

import re
from dataclasses import dataclass
from datetime import datetime

from marketplace_adapter import MarketplaceDenied, RegistrationGateway, validate_purchase


@dataclass(frozen=True)
class AgreementSnapshot:
    agreement_id: str
    status: str
    starts_at: datetime
    ends_at: datetime | None
    observed_at: datetime


def _aware(value):
    return (isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None)


class AgreementReader:
    """Return minimal fresh evidence for a resolved direct-sale purchase.

    ACTIVE describes the agreement, not whether an individual usage license has
    provisioned. Callers must not use this snapshot alone to activate resources.
    No raw AWS response, registration token or estimated charge is retained.
    """

    @classmethod
    def from_session(cls, session, seller_account, product_code, product_id):
        return cls(RegistrationGateway._client(session, 'sts'),
                   RegistrationGateway._client(session, 'marketplace-agreement'),
                   seller_account, product_code, product_id)

    def __init__(self, sts, agreements, seller_account, product_code, product_id):
        if (not isinstance(seller_account, str)
                or not re.fullmatch(r'[0-9]{12}', seller_account)
                or not isinstance(product_code, str) or not product_code.strip()
                or not isinstance(product_id, str)
                or not re.fullmatch(r'prod-[A-Za-z0-9-]+', product_id)):
            raise ValueError('Configured seller, product code and product ID required')
        self.sts = sts
        self.agreements = agreements
        self.seller_account = seller_account
        self.product_code = product_code
        self.product_id = product_id

    def describe(self, purchase, now):
        validate_purchase(purchase, self.product_code)
        if not re.fullmatch(r'[A-Za-z0-9_/-]{1,64}', purchase.agreement_id):
            raise MarketplaceDenied('Invalid agreement identifier')
        if not _aware(now):
            raise ValueError('An aware observation time is required')
        # Recheck on every read rather than trusting a previously checked session.
        identity = RegistrationGateway._call(self.sts.get_caller_identity)
        if identity.get('Account') != self.seller_account:
            raise MarketplaceDenied('AWS caller is not the configured seller')
        result = RegistrationGateway._call(
            self.agreements.describe_agreement, agreementId=purchase.agreement_id)
        if (result.get('agreementId') != purchase.agreement_id
                or result.get('agreementType') != 'PurchaseAgreement'
                or result.get('acceptor') != {'accountId': purchase.account_id}
                or result.get('proposer') != {'accountId': self.seller_account}):
            raise MarketplaceDenied('Agreement purchase identity mismatch')
        proposal = result.get('proposalSummary')
        expected = [{'id': self.product_id, 'type': 'SaaSProduct'}]
        if not isinstance(proposal, dict) or proposal.get('resources') != expected:
            raise MarketplaceDenied('Agreement product identity mismatch')
        status = result.get('status')
        if status not in {
            'ACTIVE', 'ARCHIVED', 'CANCELLED', 'EXPIRED', 'RENEWED', 'REPLACED',
            'ROLLED_BACK', 'SUPERSEDED', 'TERMINATED',
        }:
            raise MarketplaceDenied('Unknown agreement status')
        start, end = result.get('startTime'), result.get('endTime')
        if not _aware(start) or (end is not None and (not _aware(end) or end <= start)):
            raise MarketplaceDenied('Invalid agreement dates')
        # Future start and elapsed end are evidence, never silently promoted to
        # current entitlement merely because AWS still reports ACTIVE.
        return AgreementSnapshot(purchase.agreement_id, status, start, end, now)
