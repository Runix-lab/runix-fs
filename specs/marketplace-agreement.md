# Read-only seller agreement evidence

Scope, 2026-10-29: implement a credential-chain-backed AgreementReader for
DescribeAgreement, not automatic positive PAYG activation. Input is an already
resolved Purchase, never AWS IDs supplied by a public caller. No HTTP route,
worker, database state, resource creation or billing call is added.

Use the shared us-east-1 SDK factory and transport limits. Check STS seller
identity afresh on every read, then require exact agreement, PurchaseAgreement,
buyer/acceptor, seller/proposer and a single configured SaaSProduct resource.
Restrict agreement IDs to the current SDK pattern and length before AWS calls.
Reject missing evidence, unknown statuses, naive dates and nonpositive dated
windows. Preserve future starts, elapsed ends and all recognized statuses as
evidence; neither ACTIVE nor this snapshot proves a provisioned usage license.
PAYG may have no end date. Return only agreement ID, status, start/end and caller's
aware observation time; never raw responses, charges or registration tokens.
No cached result, activation flag or durable permission grant is produced.
Read errors remain unavailable, never successful verification or an automatic
negative lifecycle event. Reconciliation must separately use trusted stop guards.

The shared purchase validator accepts both license colon and slash resource
separators, as shown in AWS primary documentation. Preserve the exact ARN:
do not normalize between them, equate identities, infer its account is the buyer,
or accept other services/partitions/resource types. Supporting the documented
syntax does not broaden which product, account or agreement is bound.

Current installed botocore 1.43.118 supports GetAgreementEntitlements in
marketplace-agreement, distinct from legacy marketplace-entitlement
GetEntitlements. Its status, reason, type, product and license fields are useful
candidate evidence, but the current developer guide describes acceptor calls.
Seller/proposer access and authoritative activation semantics have NOT been
verified for this account. Do not deploy a guessed seller call, use buyer
credentials, or activate from a registration token or LicenseUpdated example.
This integration remains a release gate; the local reader deliberately does
not call GetAgreementEntitlements or claim that gap is solved.

Primary references retrieved 2026-10-29:

- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-agreements_DescribeAgreement.html
- https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-agreements_GetAgreementEntitlements.html
- https://docs.aws.amazon.com/marketplace/latest/developerguide/work-with-agreement-api-buyer.html
- https://docs.aws.amazon.com/marketplace/latest/developerguide/agreement-api-access-control.html
- https://docs.aws.amazon.com/license-manager/latest/userguide/license-signing.html

Tests must use actual botocore models and cover wrong/rotated seller,
buyer/product/agreement substitution, missing/unknown evidence, statuses,
future/elapsed/invalid dates, no-end PAYG, replay and concurrent reads, SDK errors,
configuration and pre-call validation. Add slash-ARN registration and negative
lifecycle regressions, including replay and stopped metering.

Subsequent primary-source finding, 2026-10-29: the rendered Concurrent Agreements
workshop's PAYG usage panel supplies the explicit License Updated activation
signal that the generic event example did not establish. The new local
PaygLicenseState uses that signal plus this reader's fresh agreement check and
existing negative stop guards; see marketplace-payg-license.md. It still does
not call buyer-oriented GetAgreementEntitlements, deploy trusted event transport,
provision resources or establish a real AWS buyer's license state.
