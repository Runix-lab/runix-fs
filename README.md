# Runix FS

An AI filesystem maintained by **Runix Lab**, based on the Apache-2.0
[Curvine](https://github.com/CurvineIO/curvine) distributed filesystem and cache.

[Product website](https://runixcloud.io/fs) ·
[Quick start](https://runixcloud.io/docs/fs) ·
[Development specifications](specs/README.md) ·
[Original Curvine README](README.upstream.md)

Runix FS provides the starting point for AI Agent workspaces, dataset access
and checkpoint storage over object storage. This public fork preserves the
upstream history and engine compatibility. Managed AWS delivery, subscriptions
and Marketplace integration are planned in the specs; this migration does not
ship a hosted service, Marketplace listing or a new performance guarantee.

## Start developing

```sh
git clone git@github.com:Runix-lab/runix-fs.git
cd runix-fs
git remote add upstream git@github.com:CurvineIO/curvine.git
```

Read [AGENTS.md](AGENTS.md) and [specs/README.md](specs/README.md) first.
Use the pinned Rust channel in `rust-toolchain.toml` and the upstream Linux
build environment. See the [architecture and test gates](specs/architecture.md)
for dependencies and explicit cluster/FUSE/CSI checks. The internal crate names,
`cv` CLI, config keys and CSI provisioner retain their Curvine names for
compatibility. Upstream releases are not Runix FS releases.

## Project contracts

- [Migration, copyright and contribution policy](specs/migration.md)
- [Architecture and implementation boundaries](specs/architecture.md)
- [AWS service and billing design](specs/commercial-service.md)
- [Website and account integration](specs/website-integration.md)
- [Development roadmap](specs/roadmap.md)

Every backend API change needs unit tests. Every change must have a Git commit.
Only the owner has been configured as a direct collaborator for this migration;
future access grants will follow owner-provided GitHub usernames and roles.

## License and attribution

Licensed under [Apache-2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
Original Curvine copyrights, including source notices naming OPPO, remain with
their respective owners. Runix-specific additions do not transfer ownership of
upstream work. Curvine names and links identify software origin and do not imply
upstream endorsement of Runix FS.

The original English README is preserved as `README.upstream.md`. Upstream
benchmark claims are attributed to upstream and have not been remeasured here.

Modification notice: Runix Lab replaced the product entry README on 2026-10-21
and preserved the original version separately.
