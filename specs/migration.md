# Migration and provenance contract

## Identity

- Product: **Runix FS**. Organization: **Runix-lab**.
- Repository: https://github.com/Runix-lab/runix-fs
- Website: https://runixcloud.io/fs
- Upstream: https://github.com/CurvineIO/curvine
- Initial upstream commit: `7d476508e2cd608a1aaaf7837999f52ab633811e`.
- The initial commit has 1,121 reachable commits, preserving author history.
- This is a public GitHub fork with its parent relationship retained. The
  transient name `linux-fs` was corrected to `runix-fs` at the owner's request.
- Current checkout: `/Users/cuihuan/Documents/ChatGPT/filesystem`.
- Git remotes: `origin` is Runix-lab/runix-fs; `upstream` is CurvineIO/curvine.
- The owner requested no additional collaborators. The direct collaborator
  listing contained only `cuihuan` with admin permissions at migration time.
  Organization owners and inherited policy remain GitHub organization concerns.

## Copyright and distribution

The upstream LICENSE is Apache-2.0. Preserve it byte for byte and preserve all
applicable source headers, patent, copyright, attribution and trademark notices.
The Git-tracked upstream tree at the initial commit contains no NOTICE file;
the new root NOTICE records origin and Runix-specific additions without
asserting ownership of upstream code. It does not replace dependency notices.

Apache-2.0 sections 2 and 4 permit derivatives and redistribution subject to
the license conditions. Section 4(b) requires prominent modification notices
in changed files; section 6 does not grant upstream trademark rights. Section 9
permits charging for support on one's own behalf. Runix must not describe the
fork itself as ASF/CNCF endorsed merely because upstream material mentions those
organizations. Reference: https://www.apache.org/licenses/LICENSE-2.0

The original English README is preserved byte for byte as README.upstream.md;
the Chinese README retains its content with an explicit fork banner. Newly
modified upstream files must carry a Runix modification notice. New Runix
material is distributed under the root Apache-2.0 license.

Before distributing binaries or images, generate a dependency SBOM and review
Rust, Go, Java, Python, JavaScript and bundled native libraries independently.
Include LICENSE, NOTICE, applicable dependency licenses, source revision and
modification information in each distribution. Apache licensing of this
repository is not evidence that every transitive dependency is Apache-2.0.
Commercial service terms and SLA cover Runix services, not exclusive ownership
of the open-source engine. No new commercial terms or SLA are introduced here.

## Compatibility and upstream synchronization

Rename repository/product identity first. Preserve `curvine-*` crates, `cv`,
daemon names, CSI provisioner, existing environment variables and config keys.
An indiscriminate replacement would break consumers and complicate upstream
security merges. Keep upstream documentation and benchmark attribution visible.

```sh
git remote -v
git fetch upstream main
git switch -c codex/upstream-sync
git merge upstream/main
# Run dependency, unit, cluster and FUSE/CSI gates before merging.
```

Do not force-push upstream history, push to CurvineIO, or mirror upstream
registry secrets. Upstream publication workflows are retained for reference
but gated to `CurvineIO/curvine`; Runix publication requires its own spec,
registry destinations, credentials and approval. The compile workflow remains
available for genuine engine changes. Lightweight migration CI verifies
provenance, attribution and repository guards without claiming cluster health.

## Subsequent access grants

After the owner supplies GitHub usernames, prefer Write for developers and
Maintain for release coordinators. Avoid granting organization-wide ownership.
Read back the final permission or pending invitation and report it explicitly.
Do not treat a pending invitation as accepted access.

## Verification scope

Migration verification covers fork parent, remotes, reachable Git history,
unchanged engine source and LICENSE, Runix branding, publication isolation,
documentation links, website QA and the recorded commit. Any crate unit tests
or Linux CI results must name their exact scope. Marketplace listing, tenant
onboarding, metering, cluster failover, FUSE and CSI runtime acceptance remain
separate future gates unless separately evidenced.
