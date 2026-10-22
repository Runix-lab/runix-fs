# Development roadmap and acceptance gates

This migration establishes a public fork and development baseline. The stages
below are future delivery scope, not features shipped by renaming the repository.

| Stage | Deliverable | Gate |
| --- | --- | --- |
| 0: Migration | Fork, author history, Apache attribution, README, specs, website links, memory | Repository/website checks; commits and clean working tree |
| 1: Reproducible engine | Runix Linux image/package with pinned source and toolchain | SBOM, notices, reproducible build, FUSE and cluster smoke, backup/restore |
| 2: Dedicated service | Private AWS cluster deployment, IAM/S3 isolation, operator API | Unit tests for APIs, failure/retry tests, CSI lifecycle, cross-tenant denial |
| 3: Shared Runix accounts | Organization roles, auth, service portal and auditing | SSO/session/CSRF tests; server-derived tenant; credential rotation |
| 4: Subscription contracts | Product/license mapping, entitlements, capacity enforcement | Replay/order/restart tests; no duplicate grants; independent funds review |
| 5: Marketplace metering | Usage truth, outbox, retries and reconciliation | Seller test account; UTC/rounding/partial-success tests; approved price/listing |
| 6: Shared-cluster SaaS | Strong server/worker tenant authorization and enforced quotas | Adversarial isolation/resource exhaustion, durability and load gates |

Prefer independently reviewable commits with a narrow spec, implementation,
unit tests and real runtime evidence for each backend change. Keep published
benchmarks as upstream results until a Runix measurement records hardware,
source SHA, workload, duration and raw artifacts.

No collaborators are pending now: the owner chose to work alone. Future member
grants require usernames and role choices. AWS seller identity, target region,
cluster sizing, price dimensions, identity provider and service terms are not
chosen by this migration. These decisions should be made with cost and
deployment evidence before commercial launch.
