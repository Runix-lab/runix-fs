# Marketplace progress log

## 2026-10-26, Asia/Shanghai

- Fixed RocksInodeStore overriding an explicit metadata WAL setting. Defaults
  are unchanged; smoke configuration now explicitly enables WAL. All six
  inode-store tests and rebuilt-server 4 MiB master-only, worker-only and both
  process-crash recovery comparisons passed. Historical failures are retained
  in marketplace-local-smoke.md, not silently relabelled as successes. This
  does not establish multi-master Raft durability, S3, FUSE or SaaS readiness.
- Browser extension control recovered. Reverified current account Runix Lab
  712565469991 and existing product prod-xw6kihs3wveu2: Staging, last modified
  Oct 26; Pricing configuration still says No pricing dimension. Local CLI
  still has NoCredentials. No duplicate product or release request was made.

- Executed the compiled engine, not a mock: 4 MiB CLI write/read and byte
  comparison passed in a network-disabled Linux container. Immediate master
  plus worker process-crash recovery failed with FileNotFound after 40 attempts.
  A second requested-WAL experiment also failed; the actual inode store forces
  WAL off despite the parsed setting. No engine fix or recovery success is
  claimed. Reproduction, binary/payload hashes and source findings are in
  marketplace-local-smoke.md. Runtime data was not committed. Cloud budget is
  unspent and the test container was removed after each failed run.

- Completed a first public gateway-listing survey: LiteLLM, Portkey,
  TrueFoundry, Kong Konnect Plus, Vercel AI Gateway and Tyk. Primary-source
  links, displayed prices, actual billing models and cautions are in
  marketplace-gateway-research.md. No competitor was purchased and no gateway
  product was created. FS's existing product remains separate.
- Refreshed AWS SaaS guidelines/onboarding. A contact-us/manual provisioning
  flow is permitted only with actual registration-token resolution, a stated
  turnaround and notification; it does not allow a static page to impersonate
  delivery. A public-only-private-offer restriction in the current guideline
  conflicts with some observed competitor copy; do not imitate it blindly.

- Owner explicitly selected SaaS Subscription as the sole first-release model,
  following JuiceFS's service/purchase structure. Updated the listing, service,
  roadmap and reference specification; Contract is no longer the launch candidate.
  Prices, limits and legal terms are still not approved by that model decision.
- Rechecked the actual seller UI: Runix Lab 712565469991, existing product
  prod-xw6kihs3wveu2, Staging. Resumed revision 2, selected SaaS delivery and
  attempted Next with the fulfillment URL empty. AWS rejected the missing URL.
  Cancelled this unsaved request; no dummy URL, new product or review submission.
- Subsequently submitted only the existing product's short-description update
  to describe the planned usage-based SaaS Subscription. AWS confirmed request
  b0kylklya1tnhz8qs08bosc4k Succeeded, 2026-10-26 11:17 AM GMT+8. Verified its
  detail page including the exact summary, unchanged long description, logo,
  highlights and support. Product remains Staging, not under public-launch
  review. The earlier discarded rich-text attempt was not saved.
- Linux amd64 engine build completed successfully with Rust 1.98.1 in the pinned
  upstream CI tool image: cargo build --locked --jobs 2 -p curvine-server
  -p curvine-cli -p curvine-fuse. Build took 20m55s; a dependency future-Rust
  compatibility warning was emitted. This is compilation, not write/read,
  restart, tenant-isolation, FUSE mounting or SaaS delivery verification.
- Prepared a non-deploying private smoke-test CloudFormation generator and five
  unit tests matching the approved inventory. Combined Python suite: 30 passed;
  cfn-lint 1.58.0 us-east-1 and git diff --check passed. No paid resources created.

- Owner approved the exact $5 private smoke-test budget previously proposed;
  no repeat budget approval is needed within that inventory, lifetime and scope.
  Actual cloud spending in this resumed work remains zero so far.
- Owner requested a version following JuiceFS. Prepared Runix-authored draft
  v1 in marketplace-reference-draft.md, including the usage-based candidate
  model and required unit/cost decisions. No competitor price, legal term,
  capacity limit or SLA was made effective for Runix.
- CLI STS identity check returned NoCredentials. Browser session had expired;
  owner logged in again. The live Marketplace page then confirmed Runix Lab
  account 712565469991, the existing product and Staging status. Request log
  still contained two requests. No duplicate product or seller registration.
- Preparing CloudShell as a session-bound deployment channel rather than
  requesting or extracting long-lived keys. No browser cookies were read.
- Downloaded the upstream CI build/test image pinned to amd64 digest
  sha256:841254160ea7b619964c5be225e1c5bb5891c1ec91f0d641c2a210db2701cb9d.
  This is a tool image, not a newly built or verified Runix engine artifact.
  Docker stopped before the first environment-probe container could run;
  recovery is in progress. No filesystem smoke result is claimed.

## 2026-10-23, Asia/Shanghai

- Requested workspace was an empty Git repository with no commits or specs.
  Recovered the real remote into `runix-fs/` using a shallow HTTPS clone with
  HTTP/1.1 after HTTP/2 transport failures. Base: `7cd4e0bbba0387ca6075f091f94b5bda447675c1`.
- Requested `a4602fa3` is not in this checkout; GitHub returned HTTP 422 for
  that commit. `specs/marketplace-listing.md` was absent remotely. This record
  and the new listing contract replace assumptions with current observations.
- Browser inventory worked; extension page control failed with debugger
  unavailable. Native Dia browser control worked. Opened a separate work window.
  No browser profile files or cookies were read. AWS CLI has no credentials.
- Verified seller identity, paid publishing permission and KYC states; see
  marketplace-listing.md. No new seller registration, bank/tax submission or
  binding legal acceptance was performed.
- Checked empty SaaS products and five completed/failed seller-setting requests.
  Created `prod-xw6kihs3wveu2` / `m9i25gk20n1l4tvuild27fwd`, title Runix FS Cloud
  Service; observed **Staging**. ID generation request Succeeded.
- First create-wizard save returned to Staging; the detail page initially still
  showed only the title. It subsequently completed as **Save updates**, request
  `a830jbxslo7l54441i16iua6u`, Succeeded at 16:09 GMT+8. Its request detail confirms
  the logo, short/long descriptions, three highlights, support details, Storage
  category and seven keywords. It also created an incomplete offer entity.
- A separately prepared update against revision 1 was rejected as an old
  product revision. Do not resubmit it. Its optional learning-resource additions
  were not saved; the successful original already includes the docs URL in
  support and the source URL in its description. The live site URL is in this
  specification, not yet a saved learning resource.
- Latest price configuration explicitly says **No pricing dimension**;
  fulfillment explicitly says **No fulfillment option**. No pricing model was
  selected or locked by publishing to Limited.
- No Limited visibility, paid offer, public review submission, buyer purchase,
  cluster deployment or public availability has been verified.
- Inspected live reference listing and refreshed official AWS integration docs.
  Found conflicting cancellation-window wording; PAYG remains deferred.
- Source inspection found no commercial control plane. Local website checkout
  contains unrelated uncommitted edits; none were changed or staged.
- Implemented a non-deployed ContractGateway SDK adapter and tests, preserving
  engine code and Apache attribution. boto3/botocore 1.43.118 service models
  include Concurrent Agreements fields. Nineteen adapter tests plus six existing
  migration tests pass; provenance verification, Python compilation and
  `git diff --check` pass. No real AWS API was invoked by these tests.
- Docker Desktop now reports a Linux daemon after starting the installed app;
  no Runix/Curvine image is present. No filesystem smoke or recovery result is
  claimed. The cloud test budget is prepared in marketplace-test-plan.md.

## Resume safely

1. Open the existing seller product link in marketplace-listing.md. Check its
   request log before retrying any submitted update; never recreate the product.
2. Reuse successful Save updates request `a830jbxslo7l54441i16iua6u` as evidence.
   Check latest product revision before any future update.
3. Implement the owner-selected Subscription model. Keep prices/terms and actual
   AWS fulfillment configuration empty until approved and deliverable; never
   substitute a Contract entitlement check for PAYG activation.
4. Continue beyond the SDK adapter into real identity, durable org/license
   binding, private provisioning and lifecycle handling. Unit tests are not
   evidence of deployment, end-to-end authentication, quota or storage delivery.
5. The exact $5 short-lived private test budget is approved. Stay within its
   inventory and lifetime; production and real purchase tests are not covered.

No secret, runtime usage ledger, raw registration token or customer identity
material belongs in this log or a Git commit.
