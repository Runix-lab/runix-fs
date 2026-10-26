# AWS Marketplace gateway landscape

Research date: 2026-10-26, Asia/Shanghai. Scope: AI/LLM gateways first, with
general API management as an adjacent category. This is public-listing research,
not a purchase, benchmark, exhaustive inventory or approval to publish a Runix
gateway. No competing product was subscribed to. Model inference was not called.

## Verified comparison

Prices below are displayed public table values, not negotiated quotations,
minimum purchase commitments or approved Runix prices. Delivery and pricing
classification use the actual listing fields and pricing tables, not generated
AWS "AI Insights" text, reviews or a vendor's generic SaaS delivery paragraph.

| Product / primary source | Scope | Marketplace delivery and pricing | Displayed price / qualification |
| --- | --- | --- | --- |
| [LiteLLM LLM Gateway - Self Hosted](https://aws.amazon.com/marketplace/pp/prodview-gdm3gswgjhgjo) | Unified model access, virtual-key budgets, rate limits, retry/fallback | SaaS listing for a self-hosted Enterprise offering; 12-month Contract | Table shows $0.01 for Enterprise, but title and overview explicitly require a private offer. Do not call this a one-cent enterprise purchase. |
| [Portkey AI](https://aws.amazon.com/marketplace/pp/prodview-o2leb4xcrkdqa) | AI gateway, observability, routing, prompts and guardrails | SaaS; 12-month Contract | Enterprise Plan table: $99,999 per 12 months; refund policy says Custom. |
| [TrueFoundry AI Gateway](https://aws.amazon.com/marketplace/pp/prodview-cfheeich3ggpy) | LLM, MCP and Agent gateway / governance | SaaS; 1-month and 12-month Contract options | Monthly table: Pro $6,250; Enterprise $12,500; On-Prem $16,666.66. Non-refundable except as required by law according to the listing. |
| [Kong Konnect Plus](https://aws.amazon.com/marketplace/pp/prodview-77nhc3l2cn5im) | Unified AI/API governance | SaaS; usage-based Subscription | One Pay as you go dimension at $0.01/unit; description refers to usage metered in Konnect and the vendor pricing page. This is not proof that each request costs $0.01. Public listing also offers a trial and private-offer requests. |
| [AI Gateway by Vercel](https://aws.amazon.com/marketplace/pp/prodview-cwlx232m3j4m6) | Unified model endpoint, budgets, load balancing and fallback | SaaS; Contract with additional metered usage | 12-month AI Gateway credit table: $1,000,000, with Contact Us for Private Offer Pricing. On-demand credit: $0.01/unit. Do not interpret this as a universal minimum spend or $0.01 per token/request. |
| [Tyk Cloud, Hybrid & Self Managed API Management](https://aws.amazon.com/marketplace/pp/prodview-pboluroscnqro) | General API gateway and lifecycle management; adjacent competitor | SaaS; 12-month Contract | Two Core rows each display $25,000/12 months and link to plan details. Do not sum those rows into a required $50,000 purchase. |

All six warn that additional AWS infrastructure costs may apply. That warning
does not establish whether upstream model inference costs are included. Private
offers, quantity, architecture, term and inference charges require their actual
offer documents. Vendor compliance/performance claims were not independently
verified or adopted for Runix.

## Patterns relevant to a future Runix gateway

### Managed multi-model access

Vercel is the closest named reference if the product sells hosted model access
and a unified endpoint. It is not a simple pure-Subscription example: the
observed listing combines a commitment with additional usage. Document provider
authorization/resale rights, model price changes, request-to-token accounting,
failed/partial streaming, retries and cancellation before offering inference.
The listing alone does not establish any vendor's resale rights.

### Gateway software / governance

LiteLLM is useful for Enterprise/self-hosted packaging; Portkey and TrueFoundry
for governance/support packaging. Here the software charge must be separated
from customer-provided upstream model credentials and inference charges.
Customer-hosted runtime and Marketplace SaaS classification are not mutually
exclusive: inspect the actual control-plane and service responsibilities rather
than automatically classifying every Docker deployment as an AMI product.

### Pure usage-based gateway service

Kong Konnect Plus is the clearest verified Subscription example in this sample.
Its listed billing unit represents metered Konnect usage, not an assumed token
unit. A single Marketplace dimension can aggregate a documented service unit,
but the conversion and buyer-visible breakdown must remain reproducible.

## Proposed Runix research-to-listing handoff (not selected pricing)

Working title: **Runix AI Gateway**. Keep this separate from Runix FS's existing
product ID. Do not create a gateway product until existing seller inventory has
been checked for a matching draft and the actual source/service is inspected.

1. Locate the canonical gateway source, deployed endpoint, operator, provider
   agreements and existing Runix identity/organization service. A public model
   catalog or admin screenshot does not prove fulfillment readiness.
2. Establish whether Runix sells gateway software with BYOK, model inference,
   or both. List who pays each underlying provider and AWS infrastructure bill.
3. Choose the delivery boundary and reference purchase flow based on evidence:
   Konnect for usage-based gateway service; LiteLLM for self-hosted enterprise;
   Vercel for hosted multi-model access/credits. These are recommendations from
   the sources, not claims that Runix already implements their capabilities.
4. Validate organization/key authorization, streaming and tool calls, provider
   failover without duplicate customer charges, durable usage/outbox and ledger
   reconciliation. Test retries, time boundaries, cancellation, crash recovery,
   upstream partial success and withheld credentials before charging.
5. Use AWS's actual registration and lifecycle integration, approved prices,
   original Runix terms, buyer test and public review. Do not advertise another
   vendor's capacity, certifications, model count or SLA as Runix features.

## Official requirements refreshed

- [SaaS guidelines](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-guidelines.html): authenticated access, customer isolation, subscription status, support and full Marketplace billing. The current security requirements include encryption and protected security audit logs retained for at least one year.
- [Onboarding](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-product-customer-setup.html): real registration POST/token handling and current account/license identity. Manual setup is allowed only with actual token resolution, a stated turnaround and contact/notification; a static sales page is not a substitute.
- [Pricing models](https://docs.aws.amazon.com/marketplace/latest/userguide/saas-pricing-models.html): Subscription is PAYG; Contract and Contract with PAYG are separate choices. The model cannot be changed after publishing to Limited.

The current public setup guideline says public dimensions must not be restricted
to private offers only. That creates a practical discrepancy with the observed
LiteLLM private-offer-only wording. Do not infer permission to imitate that
purchase restriction; confirm eligibility with AWS before any Runix equivalent.

## Runix FS launch boundary

Runix FS remains the owner-selected Subscription-first product, separate from
this research. Runix is derived from Curvine, not JuiceFS: aligning commercial
packaging does not make their metadata engines, durability, performance or
filesystem semantics identical. Publish only validated Runix behavior.
The existing Staging content update is not a public launch. Registration,
subscription lifecycle, private delivery and billing must work first; prices
and Runix-specific legal commitments remain approval gates.
