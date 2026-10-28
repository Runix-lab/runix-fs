# Marketplace progress log

## 2026-10-28, Asia/Shanghai

- Implemented actual RS256/RFC9068 access-token verification from a pinned
  public JWKS. Thirteen new real-signature tests pass; combined suite now 131
  passed with provenance/whitespace checks. Verified identities flow into fresh
  organization membership checks; token org/admin claims do not grant roles.
  Private signing keys exist only as ephemeral in-memory test fixtures. No
  real provider, browser login, public service or purchase is claimed.
- Actual AWS CLI identity recheck returned NoCredentials. Production budget
  remains declined. No seller identity, positive license state or paid resource
  was inferred from local tests. Previous completed goal turn produced real
  lifecycle code and a successful remote CI run; it was concrete progress.
- Committed lifecycle work as d7b0fdc. Created and pushed the review branch
  codex/marketplace-saas-integration. Fetch found a new remote main commit
  fbe0557 (Chinese quick-learn guide); merged it without overwriting its README
  or migration-test changes. Merge snapshot: d7c57e8c043f258a1b0a77d87a53e15ba5b229f8.
  Remote main was not updated and no PR/merge/release was created.
- GitHub Actions run 40620464111 completed successfully for that exact snapshot:
  https://github.com/Runix-lab/runix-fs/actions/runs/40620464111. Read actual job
  conclusions and logs: 118 Python tests, provenance/whitespace checks and 19
  Linux fault-runtime tests passed. This CI does not execute the earlier local
  S3 integration, inode-store WAL subset, FUSE, SaaS HTTP or Marketplace purchase.
  Branch code/artwork is inspectable at
  https://github.com/Runix-lab/runix-fs/tree/codex/marketplace-saas-integration.
  This is a source-review URL, not a usable SaaS or public buyer listing URL.
- Recovered the interrupted lifecycle work, completed a durable negative-event
  reducer and connected stop guards to registration, usage accumulation, sealing
  and outbox dispatch. Twenty-one new tests and all 118 combined Python tests
  passed, including process exit/reopen, stop/enqueue races, quarantine rollback
  and stop during an SDK request. Accepted/in-flight audit and source data are
  retained. No live event queue, provisioning or final-flush acceptance is claimed.
- Initial verification failed because the earlier temporary environment lacked
  dependencies. Respected the externally-managed Python refusal; created a new
  isolated verification environment and installed pinned SDK/PyYAML packages.
  Full passing verification used /tmp/runix-marketplace-verify-20261028.
- Browser automation runtime was reset. Re-selected the documented Chrome
  extension channel, listed existing AWS tabs and attempted to read the existing
  product overview (tab 563712926). Page control timed out and reset its runtime.
  Listing a tab is not proof of an authenticated session. Current seller/product
  state was not freshly verified; last verified product remains Staging. No new
  request, image upload, price, visibility change or paid resource was submitted.
- Previous completed goal turn was progress via commit c817ef6; the interrupted
  turn also wrote concrete guards/specifications. These are not live AWS waits.
  Full publication objective remains incomplete; no public SaaS URL exists.

## 2026-10-27, Asia/Shanghai

- Extracted RegistrationGateway from the Contract adapter and implemented
  durable pending claims/organization bindings, specified before code in
  marketplace-registration.md. Seventeen new tests pass; combined suite now
  97 passed, including original Contract behavior. Binding races, cross-org
  denial, expired/revoked contexts, raw-token non-persistence, process exit
  and partial binding/intent rollback were exercised. Claims/intents are local
  primitives, not an HTTP registration endpoint, SSO login or real provisioning.
- Refreshed current AWS EventBridge schema and actual SDK operation shapes.
  License Updated carries identity but the example has no explicit active
  flag; PAYG guidance excludes GetEntitlements. Final-reporting window wording
  still conflicts across official pages. No activation or cancellation deadline
  was invented to bypass those unresolved live-integration requirements.
- Previous goal turn made commit e3637af and passing new accounting tests;
  it was progress, not a live wait. No production spend, paid purchase, new
  Marketplace request, public buyer URL or visible launch is claimed here.
- Implemented exact GiB-hour interval accounting in marketplace_storage_usage.py
  with immutable source-event replay, gap/order rejection, persistent per-license
  remainders, final fractional waiver and atomic hourly outbox sealing. Nineteen
  new tests passed, including independent Fraction comparison, concurrent
  append/seal, subprocess exit and rollback after a partial multi-hour enqueue.
  Combined suite: 80 passed; provenance and whitespace checks passed. No live
  collector, organization authorization or subscription cancellation is claimed.
- The prior goal turn was concrete progress (commits 03d9de2 and 174b7d0), not a
  verified live AWS wait. Rechecked the retained product form: Session expired
  remains visible. No saved draft/price/image update, buyer URL or public
  visibility was obtained in this continuation. The explicit declined
  production budget remains in force; no paid resource was created.
- Executed real local S3-compatible integration against a temporary MinIO
  container, with the rebuilt engine and a separate official Python SDK
  container. Seed/read, write-through verified directly by S3 GetObject, and
  both-object retrieval after simultaneous Master/Worker SIGKILL/restart passed
  byte comparisons. Hashes, pinned images, failures and reproduction are in
  marketplace-local-smoke.md. This is not actual AWS S3, FUSE or SaaS delivery.
- Verified internal Docker network=true, no engine/store host port bindings,
  and no remaining test containers/networks after execution. No pre-existing
  local service was stopped. Added two failure-cleanup tests; combined suite
  now 61 passed. No AWS resources, buyer purchases or billing calls occurred.
- Continued the full launch objective with a durable PAYG metering outbox,
  specified before implementation in marketplace-metering.md. Real local
  SQLite transactions, separate-connection concurrency, subprocess exit and
  post-AWS/pre-local-commit failure are covered. Twenty-six new tests and all
  59 combined Python tests passed without real Marketplace billing. SDK
  botocore 1.43.118 and current AWS docs were checked for fields, limits and
  DuplicateRecord meaning. No organization API, license verifier or collector
  is claimed. Independent financial review and live integration remain gates.
- Updated existing Runix CI dependency installation to include the pinned
  Marketplace SDK required by these tests. Only local checks were run; no
  remote CI conclusion is claimed. Added an ignored private runtime directory;
  no usage DB, token or real customer record was committed.
- Last browser check confirmed explicit Session expired. The previous goal
  turn produced executable code and 25 passing new tests: progress, not a
  launch or live AWS wait. Product remains the existing Staging listing; no
  new saved image, price, fulfillment or release request is claimed.

## 2026-10-26, Asia/Shanghai

- Owner declined the proposed $175/month production allocation and narrowed
  immediate work to local verification and drafts. No AWS resource was created,
  no purchase was made, and no cloud smoke test was started. Do not treat the
  earlier $5 short-test approval as production authorization.
- Local original gallery artwork and logo are committed in df0f624. Uploading
  the gallery through the extension file chooser timed out; native selection
  did not attach a file. The empty gallery asset was removed from the form.
  The gallery image is **local only**, not saved to Marketplace.
- Added the verified public overview and documentation URLs to the existing
  revision-3 update form, then clicked Submit. AWS returned **Session expired:
  We can't start ChangeSet**. The Sign in link opened the AWS login page; no
  new request ID or successful save was obtained. Do not report these resource
  links as saved, or blindly resubmit against a stale revision after login.
  The existing tab retains the unsaved form for recovery. No legal terms,
  price, fulfillment endpoint or visibility were submitted.
- Re-ran all 33 Python tests successfully. Earlier six Rust inode-store tests
  and three real process-crash smoke runs remain separately scoped evidence.
  No new backend interface was introduced in this continuation.

- Owner delegated initial price-setting using JuiceFS as the reference, rather
  than supplying a rate. Prepared marketplace-launch-commercial-draft.md:
  $0.00002740/GiB-hour (about $0.02/GiB at 730 hours), integer/remainder rules,
  explicit infrastructure cost gap and proposed policies. This supersedes
  asking the owner for a price number. Legal terms remain unapproved; the
  subsequently proposed $175/month production ceiling was declined above.

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
5. Current instruction is local and draft work only. The previous exact $5
   short-lived cloud test approval does not authorize production or purchases;
   do not start it while the narrowed immediate scope remains in force.

No secret, runtime usage ledger, raw registration token or customer identity
material belongs in this log or a Git commit.
