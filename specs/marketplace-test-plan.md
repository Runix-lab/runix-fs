# Marketplace delivery verification and budget proposal

Status: proposed, not approved or provisioned. Prices checked 2026-10-23.
This plan does not authorize any charges. No production capacity or SLA follows
from a small functional test.

## Local preparation

Docker Desktop was installed but its daemon initially was stopped. Starting the
existing app made `docker info` report Linux. No Runix or Curvine engine image
was present locally. The Python Marketplace adapter tests run without AWS access;
they do not establish filesystem or deployment behavior. Build a pinned Runix
Linux artifact and record image digest, notices and SBOM before the cloud test.
Do not start billable instances while waiting for a lengthy dependency build.

## Proposed private AWS smoke environment

Region: us-east-1. Use synthetic test data only. Proposed maximum lifetime:
two hours after readiness of the prebuilt image and deployment access.

| Resource | Quantity and limits | Estimate basis |
| --- | --- | --- |
| Isolated VPC/subnet/route table/security groups | Two isolated test tenant boundaries, one AZ each | No NAT, public IP, Internet-facing engine listener or load balancer |
| Linux EC2 t3.large | Four instances: one master and one worker/client per test tenant | 4 x 2 h x $0.09 allowance = $0.72 |
| Encrypted gp3 | Four 20 GB roots plus two 40 GB worker volumes; 160 GB total | 160 x $0.08 x 2/720 = about $0.036 |
| SSM interface endpoints | ssm and ssmmessages in each VPC, four endpoint ENIs total | 4 x 2 h x $0.01 = $0.08, plus data processing |
| S3 gateway endpoints | One per VPC | No endpoint hourly charge |
| S3 storage/artifact and backup buckets | At most 1 GB synthetic data, bounded request count | Allow $0.20 for the short test; recheck region rates before provisioning |
| Logs and miscellaneous transfer | At most 0.5 GB logs and 1 GB total test transfer | Allow $0.50; no cross-region traffic |
| IAM roles/profiles | Restricted instance access to its own bucket/prefix and SSM | Review exact policies before granting access; no persistent access keys |

Expected short test: roughly **$1-$3 before tax**. Proposed authorized test
budget: **$5**, excluding any Marketplace subscription. The $0.09 instance-hour
is a conservative planning allowance, not a claimed live EC2 tariff. AWS's T3
table currently displays $0.0835 for t3.large, while its us-east-1 prescriptive
example uses $0.0832. Re-price in the target account before launch; request a
revised budget if prerequisites or quoted costs no longer fit.

Set T3 credit specification to Standard to avoid surplus-credit charges; this
test measures correctness, not production throughput. Tag all test resources
with task, owner and expiry. Prepare an independently runnable cleanup inventory
and verify resource removal after the approved synthetic-data test. A billing
alarm is not a hard spending cap. Do not leave instances/endpoints running
overnight. No continuing production environment is covered by this proposal.

Sources: [T3](https://aws.amazon.com/ec2/instance-types/t3/),
[us-east-1 instance example](https://docs.aws.amazon.com/prescriptive-guidance/latest/optimize-costs-microsoft-workloads/right-size-selection.html),
[EBS](https://aws.amazon.com/ebs/pricing/),
[PrivateLink](https://aws.amazon.com/privatelink/pricing/),
[gateway endpoints](https://docs.aws.amazon.com/vpc/latest/privatelink/gateway-endpoints.html).
Storage, log and transfer allowances above are estimates, not price quotations.

## Real service tests after budget and access approval

1. Pin source/image versions and record deployment results and private endpoints.
2. Mount, create/write/fsync, read and compare SHA-256; restart worker and master,
   remount and repeat; separately test pending asynchronous UFS writes.
3. Back up metadata and journal plus object data, restore into a fresh boundary,
   and verify hashes. Bucket object recovery alone is not metadata recovery.
4. Verify both tenant networking and authorization. Cross-tenant network traffic,
   organization identities and engine credentials must be denied. A blocked
   network path alone does not prove organization authorization.
5. Exercise quota exhaustion, concurrent reservations, failed provisioning,
   retry, rollback and crash recovery after the real control plane exists.

The one-master topology cannot demonstrate HA or a production SLA. A separate
three-master failure-domain test and cost estimate are needed for HA claims.

## Marketplace buyer test, separately gated

There is no pricing dimension or fulfillment endpoint configured on the Staging
product. The real purchase test amount is therefore **undetermined**, not zero.
Do not accept an offer until the owner approves the actual displayed charge,
buyer test account, contract duration and cancellation/refund arrangements.
Never subscribe to JuiceFS for this verification.

After identity, provisioner, policy and pricing approval: allowlist the test
buyer, publish only to Limited, and test a valid purchase, immediate token
redemption, existing/new account flow, email confirmation, organization binding,
duplicate callback, same AWS account with concurrent licenses, expired entitlement,
cancel/renewal, event replay/order, queue redelivery, crash recovery and export.
The current adapter tests do not replace these scenarios.

Only then connect the public website CTA to the actual Marketplace buyer URL
and deployed onboarding URL, submit public review, and verify the buyer page
from an independent account. Record public visibility separately from request
success or review approval.
