# Runix FS Cloud Service: reference-shaped draft v1

Prepared 2026-10-26 after the owner's instruction to prepare a version following
JuiceFS. This is Runix-authored copy and a commercial-model comparison, not a
copy of another vendor's EULA, artwork, performance promises or service limits.
Use the existing Staging product `prod-xw6kihs3wveu2`; do not create another.

## Title

Runix FS Cloud Service

## Short description

An S3-backed distributed file system and cache for AI datasets, model files,
and Agent workspaces. Runix FS combines the Apache-2.0 Curvine engine with a
commercial service offering that is currently in preparation.

## Overview

AI workloads need a common way to access datasets, model artifacts and working
files. Runix FS provides a distributed file-system namespace and caching over
S3-compatible object storage. Applications can access files through supported
filesystem clients, while workers cache data close to the workloads that use it.

Runix FS is maintained by Runix Lab and derives from Curvine under Apache-2.0.
The open-source software is available independently of any commercial service.
The proposed paid offering covers an explicitly agreed deployment, operations
and support scope. It does not replace or restrict the open-source license.

Commercial Marketplace onboarding is not yet available. Deployment boundaries,
capacity limits, service levels and recovery objectives will be specified only
after validation. Customers must pay any AWS infrastructure charges incurred
in their own AWS accounts separately from the Marketplace service fee. Runix
does not claim endorsement by Curvine or JuiceFS.

## Highlights

- File-system access and caching over S3-compatible storage for AI datasets and
  model artifacts.
- A shared engine foundation for training data, model distribution and Agent
  working files, with deployment requirements evaluated per workload.
- Apache-2.0 source availability and explicit separation between open-source
  software and the proposed managed-service/support scope.

## Packaging: follow the reference experience

Use the same navigable sections: Overview, Highlights, Pricing, Legal, Usage
and Support. The target journey is Marketplace purchase -> Runix registration
or existing-account login -> verified license -> organization binding -> actual
private resource provisioning -> connection instructions and subscription status.
Every arrow after purchase remains a delivery gate until exercised end to end.

Candidate delivery ownership: seller-operated control plane with isolated data
plane boundaries. Confirm AWS eligibility for the chosen deployment and image
distribution before completing fulfillment configuration. An engine dashboard
is not the account/subscription console.

## Pricing model comparison against the reference

The [reference listing](https://aws.amazon.com/marketplace/pp/prodview-beu22bg5b24ww)
currently displays one Professional dimension at $0.02/GiB/month, usage-based
billing without a fixed end date, cancellation at any time, possible additional
AWS infrastructure charges, and its own no-refund policy. It also advertises
10 PiB, 100M inodes and 1000 clients. These are reference observations only.

For a JuiceFS-shaped experience, Runix's **candidate** is SaaS Subscription
with one clearly defined storage-usage dimension. This differs from the earlier
Contract-first recommendation and is not yet a selected or published model.
The reference's $0.02 figure may be used in cost comparison; no Runix charge
has been approved or made effective by this document.

Before configuring any rate, resolve these concrete implementation choices:

- Bill logical stored data, provisioned storage, or another measured service
  quantity; cached copies and S3 bytes must not accidentally be double-counted.
- Define GiB as 2^30 bytes and specify the exact time aggregation, integer AWS
  quantity, rounding and monthly/hourly conversion. A $/GiB/month reference is
  not permission to charge the same amount for every GiB-hour.
- Measure resource cost and minimum sustainable price for a small dedicated
  customer. Do not assume the competitor's shared-service cost structure.
- Implement durable usage and an immutable outbox, partial-result retry,
  reconciliation and the account/license lifecycle before enabling PAYG.
- Obtain AWS clarification on the conflicting cancellation-window descriptions
  recorded in marketplace-listing.md.

Keep actual price, quantity limits and term fields empty in Staging until those
decisions are approved and the chosen model is deliverable. Do not publish to
Limited merely to save a pricing-model selection.

## Legal and support fields

EULA/MSA, privacy/data handling, refund rules, support coverage, SLA and data
retention/export remain Runix-specific approval items. The competitor's legal
terms are not adopted by reference. No legal agreement is accepted here.

Product information: https://runixcloud.io/fs

Documentation: https://runixcloud.io/docs/fs

Existing early-access/sales inquiries: sales@runixcloud.io

Fulfillment URL: leave empty until a real HTTPS POST registration backend is
deployed and tested. A static page, mailto link, or placeholder returning success
cannot fulfill a Marketplace purchase.

## Draft acceptance

The existing saved English listing can remain the conservative Staging version.
This v1 provides the reference-shaped target for later copy updates. It does not
claim that identity, quotas, storage recovery or billing have been deployed.
Public listing requires the tests in marketplace-test-plan.md and separate
verification of the actual buyer-visible product page.
