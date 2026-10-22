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
| [Website](website-integration.md) | Public website and future authenticated console integration |
| [Roadmap](roadmap.md) | Dependency order and acceptance gates for subsequent development |

Every backend API change must include unit tests for success, validation,
authorization, failure and applicable replay/concurrency behavior. Every change
must be committed. Runtime evidence must be reported separately from source
inspection. Upstream crate, binary, protocol and config names remain compatible
until a separately specified migration is tested.
