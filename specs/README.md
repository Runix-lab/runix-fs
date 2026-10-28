# Runix FS specifications

Status: migration baseline, 2026-10-21 (America/Los_Angeles).

Runix FS is the Runix Lab derivative of Curvine. Read these contracts before
changing code. Design describes planned work unless a section explicitly gives
implementation and verification evidence.

| Contract | Purpose |
| --- | --- |
| [Migration](migration.md) | Repository, branding, licensing, CI and ownership |
| [Architecture](architecture.md) | Source map and verified implementation boundaries |
| [Commercial service](commercial-service.md) | AWS delivery, identity, entitlement and metering design |
| [Marketplace listing](marketplace-listing.md) | Seller evidence, draft identity, publication gates and outstanding commercial decisions |
| [Initial commercial draft](marketplace-launch-commercial-draft.md) | Delegated reference-based pricing, exact units, cost gap and proposed policies |
| [Metering and storage ledger](marketplace-metering.md) | Exact byte-time conversion, durable sealed-record dispatch, leases, SDK responses and verification limits |
| [Registration binding](marketplace-registration.md) | SDK resolution, private pending claims, durable organization authorization and unimplemented SSO/HTTP boundaries |
| [Negative lifecycle events](marketplace-lifecycle.md) | Durable stop guards, held final usage, event replay and live-transport limitations |
| [Gateway research](marketplace-gateway-research.md) | Verified AI/API gateway listings and future product packaging, separate from FS launch |
| [Local engine smoke](marketplace-local-smoke.md) | Write/read, historical crash failure, WAL fix, local S3-compatible write-through and recovery evidence |
| [Website](website-integration.md) | Public website and future authenticated console integration |
| [Roadmap](roadmap.md) | Dependency order and acceptance gates for subsequent development |
| [Verification](verification.md) | Actual migration tests, CI results and publication boundaries |

Every backend API change must include unit tests for success, validation,
authorization, failure and applicable replay/concurrency behavior. Every change
must be committed. Runtime evidence must be reported separately from source
inspection. Upstream crate, binary, protocol and config names remain compatible
until a separately specified migration is tested.
