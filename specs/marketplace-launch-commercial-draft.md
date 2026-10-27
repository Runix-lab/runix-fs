# Runix FS initial commercial configuration

Prepared 2026-10-26, Asia/Shanghai. The owner delegated initial price-setting
to the agent with JuiceFS as the direct reference. This supersedes the earlier
requirement for the owner to supply a numeric rate. It is not an authorization
to invent delivery capabilities or sign unreviewed legal terms. No customer
absence assumption may bypass buyer acceptance or service readiness.

## Selected initial rate

Model: **SaaS Subscription**, usage-based, no prepaid contract commitment.

Reference: [JuiceFS public listing](https://aws.amazon.com/marketplace/pp/prodview-beu22bg5b24ww)
currently advertises $0.02/GiB/month. Its limits, SLA and proprietary software
are not Runix capabilities and are not copied.

Runix's proposed concrete AWS rate: **USD 0.00002740 per GiB-hour** of logical
live file storage. At 730 hours, 1 GiB costs $0.020002, approximately the
reference's $0.02. The real bill uses GiB-hours, not a fixed calendar-month fee;
672-hour and 744-hour months differ. Do not advertise exactly $0.02 per calendar
GiB-month while billing this hourly rate. The eight-decimal hourly rate follows
the AWS rate field precision. No rate has been made live in the console.

Candidate immutable dimension key: `storage_gib_hour`. Buyer description:
`Logical file storage, GiB-hour`. Use the console's supported generic Units
category if it does not provide GiB-hours. Validate the actual offered unit
before saving this immutable API key.

Definition: GiB = 2^30 bytes. Integrate logical live file bytes over active
service time in UTC, divided by 2^30 * 3600 to obtain GiB-hours. Exclude cache
copies, replication, metadata, sparse holes and unused provisioned capacity.
This measurement is a required implementation contract, not an existing metric.
Do not start billing while a subscription is waiting for usable provisioning.
The local storage interval ledger now implements exact conversion and remainder
accounting from trusted completed intervals, but actual engine measurement and
its provenance remain unimplemented. Synthetic tests do not validate a live
logical-byte metric, sparse-hole exclusion or buyer isolation.

Persist sub-unit remainders per license. Submit integer quantities only after
durable hourly sealing; never round every sample up. At final settlement,
waive any sub-GiB-hour remainder rather than inventing an extra unit. The
selected rule must be explained in the buyer's usage page and tested across
time boundaries, cancellation, duplicate submission and crash recovery.

Examples before AWS tax, platform fees or underlying infrastructure:

| Logical usage | Hours | Service fee at the exact hourly rate |
| --- | --- | --- |
| 1 GiB | 730 | $0.020002 |
| 1 TiB (1024 GiB) | 730 | $20.482048 |
| 1 TiB | 744 | $20.87485440 |

AWS infrastructure charges in the buyer's account are separate. Charges in
Runix's account are Runix's responsibility and cannot be silently passed on as
unlisted fees. No throughput, client-count, capacity or availability guarantee
is inferred from these examples.

## Sustainability check: reference price is not reference cost

The existing plan uses private dedicated test boundaries rather than JuiceFS's
managed metadata architecture. At the conservative prior planning allowances,
one continuously running two-node t3.large boundary costs approximately:

| Item | Illustrative monthly allowance, 730 hours |
| --- | --- |
| Two t3.large, Standard CPU credits, $0.09/hour allowance | $131.40 |
| 80 GB encrypted gp3, $0.08/GB-month allowance | $6.40 |
| Two SSM interface endpoint ENIs, $0.01/hour allowance | $14.60 |
| Bounded control-plane, logs, S3 and backup allowance | $15.00 |
| Total planning amount | $167.40 before tax |

These are planning allowances from marketplace-test-plan.md, not a live AWS
quotation. Re-price, confirm instance support and validate the service topology
before creating anything. One master is not HA. Backups, quota enforcement,
authenticated private connectivity and teardown must exist before production.

At 1 TiB/month, the approximate $20.48 service revenue does not cover this
dedicated infrastructure. The proposed rate is therefore an introductory price
with an explicit subsidy risk, not a proved sustainable margin. Before public
launch, either approve the seller-funded production allocation or establish a
validated lower-cost delivery boundary. Do not invent a minimum fee to close
the gap without publishing and authorizing it.

The owner explicitly **declined** the proposed $175/month production ceiling
and instructed: "不批准，先完成本地和草稿". Continue local verification and
Staging preparation only; do not create ongoing paid resources or start the
cloud smoke test under this narrowed immediate scope. The earlier $5 approval
covered only the named two-hour test, never production. No cloud resources were
created by this work. Any later production plan requires a new decision; do not
keep presenting the declined ceiling as pending approval.

## Proposed policy text for owner/legal review (not effective)

These are Runix draft decisions, not an assertion of industry-standard terms.
Do not upload or accept them as a final agreement before reviewing the actual
EULA/privacy documents and validating the corresponding capabilities.

- Availability: no contractual uptime SLA or automatic service-credit promise
  in the initial offer. This does not waive statutory obligations.
- Cancellation: buyers cancel through AWS Marketplace; stop new billable usage
  at the verified subscription boundary and settle only eligible prior usage.
- Refunds: consumed service fees are ordinarily non-refundable, except billing
  errors, mandatory law or a refund approved by Runix. Contact the existing
  sales/support address for review; do not copy another vendor's EULA.
- Data: proposed seven-day post-cancellation export window, no ongoing software
  storage fee during that window, no automatic customer-data deletion until the
  approved policy, notices and export path are implemented. Underlying AWS
  charges remain attributable to the owning account. Retention beyond seven
  days and legal holds require a separately approved policy.
- Support: existing sales@runixcloud.io and documentation, best effort without
  an invented 24/7 or response-time commitment. Verify the channel before launch.

Legal entity, jurisdiction clauses, privacy practices and bank/tax details must
come from verified Runix records and legal review, not from a competitor.

## Remaining release gates

The pricing delegation closes the missing-price-input question. It does not
close registration, authenticated organizations, PAYG license lifecycle,
provisioning, persistent metering, S3 durability, backup/restore, policy approval,
production budget, Limited buyer testing or public review. Current product
`prod-xw6kihs3wveu2` remains Staging until those gates are actually passed.
