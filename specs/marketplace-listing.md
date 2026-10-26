# Runix FS Marketplace listing

Status: non-public Staging product, re-observed 2026-10-26 (Asia/Shanghai).
This is not a public offer, an approved price, or a delivered SaaS service.
Resume the existing product; do not create another registration or listing.

## Verified seller and product

- Console account: Runix Lab, `712565469991`; seller legal name: Runix AI Inc,
  United States. The session is root (KYC says secondary verification is not
  required for root user). Do not deploy production services using root credentials.
- Partner Central account and Marketplace account both display Active.
- Marketplace Settings explicitly says **Publish paid and free products**.
  KYC business verification is Under review; bank verification is Not started.
  This KYC status is distinct from the paid publishing permission displayed.
- Tax interview and DAC7 display Completed. No tax identifiers, bank details,
  identity documents or credentials were copied or submitted during this work.
- SaaS products initially displayed No products to display. Request history
  contained five terminal seller-setting requests, not a pending Runix product.
- Created title: **Runix FS Cloud Service**.
- Product ID: `prod-xw6kihs3wveu2`.
- Product code: `m9i25gk20n1l4tvuild27fwd`.
- Seller detail: https://aws.amazon.com/marketplace/management/products/prod-xw6kihs3wveu2/overview
- No verified buyer URL, public offer, price, review approval or public launch.

## English content and assets

Short description:

> S3-backed distributed file system and cache for AI datasets, model files, and
> Agent workspaces. Planned usage-based SaaS Subscription; commercial onboarding
> is in preparation.

This summary update succeeded on 2026-10-26 at 11:17 AM GMT+8, request
`b0kylklya1tnhz8qs08bosc4k`. The request detail confirms the new short description
and preserved long description, logo, highlights and support information. This
is a Staging content update, not pricing-model configuration or launch approval.

The detailed draft describes the Apache-2.0 Curvine derivative, distinguishes
the proposed managed service from the open-source engine, and explicitly states
that automated Marketplace onboarding is unavailable. It promises no capacity,
throughput, recovery objective, client count or SLA. Replace preparation wording
with measured delivery facts before asking for public review.

Highlights: S3-backed file access/caching; preserved Apache-2.0 attribution;
per-customer evaluation during early access. Category: Storage. Keywords:
distributed file system, S3, AI datasets, model files, Agent workspaces,
distributed cache, file storage.

Use https://runixcloud.io/fs and https://runixcloud.io/docs/fs as information
resources, not fulfillment endpoints. Both docs and https://fs.runixcloud.io
returned HTTP 200 in independent public HTTP checks. This proves reachability,
not authentication, registration POST handling, or working storage.

Logo source: https://runixcloud.io/assets/logo.svg. Rasterize that existing
brand asset to a transparent 320x320 RGBA PNG for the console's 120-640 pixel
requirement. Preserve the original source; do not use competitor artwork.
Existing public sales contact: sales@runixcloud.io. Paid support scope still
requires approval; publishing an address does not verify mailbox operations.

### Pending local materials, not saved in AWS

- Original opaque 780x439 gallery PNG:
  `images/marketplace/runix-fs-overview-780x439.png`. Source/provenance and render
  instructions are in that directory's README. It is product-preview artwork,
  explicitly stating commercial onboarding is in preparation, not a screenshot
  of a working service. The existing saved logo remains unchanged.
- Learning resource name: `Runix FS product overview (early access)`;
  URL: `https://runixcloud.io/fs`.
- Learning resource name: `Runix FS documentation and quick start`;
  URL: `https://runixcloud.io/docs/fs`.

The 2026-10-26 gallery chooser did not attach a file. Submitting just the two
resource links returned **Session expired**, before AWS could start a ChangeSet.
No new request ID was obtained. The current browser form is unsaved; after
session recovery check the real revision/request log before applying this list.
The owner declined ongoing production spending and requested local/draft work
only. No price, fulfillment, Limited visibility or public review is configured
by these pending materials.

## Reference product observations

[JuiceFS listing](https://aws.amazon.com/marketplace/pp/prodview-beu22bg5b24ww)
was read without subscribing. It is SaaS, category Storage, usage-based with one
Professional dimension. The page displays $0.02/GiB/month and limits of 10 PiB,
100M inodes and 1000 clients. Those are competitor claims and are not Runix
prices or capabilities. It states no refunds, cancellation at any time, links
an EULA and multiple support channels, and warns of possible additional AWS
infrastructure charges. The actual post-purchase signup was not exercised.

Reuse the overview/highlights/pricing/legal/usage/support structure. Runix's
purchase must lead to its own authenticated onboarding, not sales email or a
static marketing page. Do not reuse the reference's terms or performance claims.

## Model decision before Limited visibility

| Model | Required implementation | Runix decision |
| --- | --- | --- |
| SaaS Subscription | Durable usage truth, hourly metering, license lifecycle, retries and settlement | Owner-selected first launch; implementation and approved rate required |
| SaaS Contract | Fixed purchased entitlement, enforced capacity, term/renewal, verified provisioner | Outside first launch; earlier recommendation superseded |
| Contract with PAYG | Both contract enforcement and metered overage | Outside first launch |

On 2026-10-26, resumed creation of this existing product (revision 2). The
fulfillment step displayed SaaS and API-Based Agents & Tools; selected SaaS.
Clicking Next with no fulfillment URL was rejected with a required valid URL
error. No placeholder URL was entered. Cancelled the unsaved request rather
than asserting a working registration service. The pricing-model step was not
reached and no release or new change request was submitted by that attempt.

[AWS pricing rules](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-pricing-models.html)
say the pricing model cannot change after publication to Limited. Do not lock
the choice by completing that transition. All-zero pricing can convert a listing
to Free, so do not use zero as an unapproved placeholder.

Candidate contract dimension: `dedicated_cluster`, integer count of dedicated
clusters with a separately specified capacity profile. Quantity is not GiB used.
Do not create this dimension until instance sizing, hard capacity, term and price
are approved. A logical capacity unit is acceptable only once enforced and tested.

## Publication blockers and implementation order

1. Approved service ownership/deployment boundary, region, capacity, support,
   contract duration, price, refund policy, SLA and retention/export rules.
2. Reproducible Linux engine image; real write/read/restart and restore evidence.
3. Seller-operated control plane with real identity provider and organization
   roles; durable unique license binding and an idempotent provisioning outbox.
4. Verified private data plane, isolation, enforced quotas, rollback and recovery.
5. Marketplace registration adapter and contract entitlement reconciliation,
   followed by authenticated HTTP routes and durable EventBridge processing.
6. Test buyer allowlisting and approved purchase cost; end-to-end subscription,
   replay, cross-organization denial, expiration and data export tests.
7. Final legal review, then Limited testing, AWS review and independent buyer
   visibility checks. Record each state separately.

The current source has no public commercial HTTP routes, provisioner, account
service or billing ledger. Do not put success placeholders in their place.
Website source is `cuihuan/runix-site`; the existing local checkout has many
uncommitted changes and older generators. Inspect remote source before edits;
do not deploy or commit those unrelated local changes.

## AWS integration evidence, refreshed 2026-10-23

- [ResolveCustomer](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_ResolveCustomer.html): new integrations use account and LicenseArn; AgreementId is under Metadata. CustomerIdentifier may be absent. Call from the seller account.
- [GetEntitlements](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-entitlements_GetEntitlements.html): filter by product, account, license and dimension; follow NextToken even after an empty page.
- [BatchMeterUsage](https://docs.aws.amazon.com/marketplace/latest/APIReference/API_marketplace-metering_BatchMeterUsage.html): use license-based records without request-level ProductCode; never dual-submit legacy records. Limits: 25 records, less than 1 MB, less than 24 hours old; previous-month cutoff 06:00 UTC on day one. Retry only unprocessed records with unchanged quantities.
- [Contract integration](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-integrate-contract.html): June 1, 2026 Concurrent Agreements requirement; sellers registered after July 15, 2026 use EventBridge. Root status and an automatically displayed SNS ARN do not establish the registration date or operational SNS eligibility.
- [EventBridge](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-eventbridge-integration.html): use source aws.agreement-marketplace, reconcile license changes with AWS; direct sellers can receive proposer rather than duplicate manufacturer agreement events.
- [Subscription lifecycle](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-subscriptions.html) and the EventBridge page disagree on whether the final one-hour reporting window starts at agreement end or license deprovision. Keep PAYG disabled until AWS clarifies the applicable lifecycle; stop new charge accumulation immediately on cancellation and do not extend billing based on the later interpretation.
- [SaaS guidelines](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-guidelines.html): control plane ownership, secure onboarding, customer isolation and buyer test evidence are release gates. BYOC image/container delivery has separate listing requirements. Do not claim deployed-on-AWS status without review.

## Next implementation slice and tests

Implement a small SDK adapter outside the engine hot path before deploying HTTP
routes. Verify the seller STS identity, resolve registration tokens, validate the
configured product and Concurrent Agreements identifiers, and evaluate a single
integer Contract entitlement. Fail closed on AWS errors, wrong identities,
expiry, malformed quantities, duplicate grants and pagination loops. Do not log
tokens, cache entitlements as permanent grants, bind organizations, provision
clusters, or charge money in this adapter. Use current botocore service models
and Stubber tests, without AWS credentials or live purchases.

This slice is reusable implementation groundwork, not completion of the service.
HTTP registration needs immediate token redemption plus durable opaque handoff;
org binding additionally needs a real authenticated principal and atomic unique
license ownership. Implement those only with those dependencies, never by trusting
an organization ID submitted by the browser.
