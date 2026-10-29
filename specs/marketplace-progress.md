# Marketplace progress log

## 2026-10-28, Asia/Shanghai

- Commits bd69406 (signed access tokens) and 0d5189c (HTTP boundary) are pushed
  to codex/marketplace-saas-integration. Exact code snapshot
  0d5189c1f9f413f947803e6ca97da8fceead06ec passed GitHub Actions run
  40624083374: https://github.com/Runix-lab/runix-fs/actions/runs/40624083374.
  Read remote logs confirmed 153 Python tests, 19 Linux fault-runtime tests,
  provenance and whitespace checks passed. These include local HTTP requests
  with synthetic signed identities and SDK Stubber, not real buyer activation.
  No Marketplace publication, identity provider or AWS deployment was created.
- Connected actual local HTTP registration, binding, organization and purchase
  routes to signed access-token verification and the durable registry. Twenty-two
  new tests and all 153 combined Python tests pass. Actual loopback requests
  exercise real RSA signatures and SDK Stubber; this is not a real Marketplace
  purchase. Pending states/readiness 503 remain explicit; no fake cluster or
  endpoint is returned. Temporary test server and keys are cleaned up.
- Added bounded SDK factory connection/read timeouts and retry counts, checked
  against current botocore documentation and covered by both factory tests.
  The HTTP runner requires verified operator configuration and seller identity,
  binds only loopback and does not ship an invented identity-provider setup.
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

## 2026-10-29 — read-only agreement evidence and ARN interoperability

Continued within the owner's latest local/draft-only scope. No production or
short-lived cloud resources, paid subscriptions, billing calls, tax/bank changes
or legal acceptance occurred. Production budget remains declined.

Found and fixed a concrete registration/lifecycle interoperability bug: the
shared purchase validator only accepted `license:...`, while current AWS
GetAgreementEntitlements examples also return `license/lic-...`. Both documented
resource separators are now accepted without normalization or changing immutable
identity bindings. Actual SDK ResolveCustomer and durable cancellation/replay
regressions cover the slash format; malformed/foreign resource strings still fail.

Added `marketplace_agreement.py`, an internal read-only DescribeAgreement adapter:
fresh seller STS check on every read; resolved buyer/agreement identity and exact
configured SaaS resource checks; minimal immutable status/time snapshot; sanitized
SDK failures. Tests cover substitution, missing evidence, all known SDK statuses,
future and elapsed windows, invalid dates, replay and concurrent reads. It has no
HTTP exposure, activation flag, persistence, provisioning or billing side effect.

Re-read current AWS primary documentation and the installed botocore 1.43.118
models. GetAgreementEntitlements is present in marketplace-agreement and differs
from the legacy Contract GetEntitlements API. Its current developer walkthrough
is buyer/acceptor oriented; seller access and authoritative PAYG activation for
this account remain unverified. DescribeAgreement ACTIVE alone is deliberately
not treated as a provisioned license. See marketplace-agreement.md for sources,
contract and remaining gate.

Validation: all **168 Python tests pass locally**; provenance/attribution verifier
and `git diff --check` pass. This uses SDK Stubber and synthetic identities, not
real AWS agreement/license evidence. No new Rust/engine change in this step.

Browser channel: Chrome extension enumerated existing Runix seller-page tabs,
but the live DOM read timed out and reset its session. Tab metadata does not prove
login or product state. No console mutation or new ChangeSet is claimed. Last
verified product state remains Staging (`prod-xw6kihs3wveu2`); current state is not
freshly confirmed. No public buyer page or delivered SaaS endpoint exists in the
evidence. Fulfillment URL and price dimensions remain unconfigured as last seen.

Remote verification: implementation commit
`07344f5bd1432ce88bf9354a15941abb63a8c88c` was pushed to
`codex/marketplace-saas-integration`. GitHub Actions run **40812595351** completed
with **success**, confirmed with `gh run watch --exit-status`:
https://github.com/Runix-lab/runix-fs/actions/runs/40812595351
This is source/CI verification, not seller API access or public delivery evidence.

## 2026-10-29 — real independent local delivery boundaries

Previous goal turn was progress: seller agreement adapter/ARN repair committed,
pushed and verified in CI. This turn advances the actual engine deployment
boundary within the owner's local/draft-only instruction; no production budget
or paid purchase authorization was inferred from the general launch objective.

Docker initially reported the daemon unavailable. Existing Docker Desktop start
command returned already running, and subsequent `docker info` verified Linux
28.5.1. Used only already cached immutable images and existing read-only build
volume. No package/image installation or existing service modification occurred.

Added repeatable local_tenant_smoke.py and local_tenant_probe.py plus 10 fault/
negative-control tests. Two fresh internal networks, independent stores, distinct
credentials/state/payloads, no published ports. Actual read/write/write-through
and crash/restart comparison passed for both boundaries. Both peer-network and
foreign-credential probes denied access while positive own-store controls passed.
Final run also inspected the real engine: no peer credentials, no host port
bindings, no privilege, read-only build volume. All owned containers/networks
were confirmed removed by fresh inventories; unrelated services preserved.

Two actual runs passed; the final one separated peer credentials into a probe-
only file, never engine/store environment. Full hashes, private evidence paths,
reproduction command, unit-test correction and limitations are documented in
marketplace-local-smoke.md. Runtime files/credentials are excluded from Git.
All **178 Python tests pass locally**; new scripts compile, provenance checks and
whitespace checks pass. No new Rust source or binary build is claimed.

This is local deployment/network/storage-boundary evidence, not production SaaS
isolation or AWS buyer testing. Still no public registration endpoint, real IdP,
positive license activation, cluster provisioner, authoritative usage collector,
hard quotas or deployed lifecycle transport. Latest actual AWS state remains
unrefreshed after browser timeouts; last confirmed product is Staging. No new
ChangeSet, fulfillment configuration, price dimension, public review or listing.

The earlier documentation-only commit d979297 remains local after repeated
GitHub HTTPS connection failures. Retry pushing the combined new commits after
local verification; record actual remote result separately. This is a transport
failure, not a reason to rewrite/force-push the work branch or claim publication.

Publication/CI follow-up: first push returned GitHub server-side `commit_refs`
failure. Read-only GitHub ref inspection confirmed the branch still at 07344f5.
A normal retry then succeeded, advancing it to
`14e8e2d2602dd7f31933d8cb2c64134db42ba0e3`, including the earlier d979297 docs.
No force push or remote history rewrite. GitHub Actions run **40814083285** for
that exact implementation SHA completed with **success**:
https://github.com/Runix-lab/runix-fs/actions/runs/40814083285
Remote CI is unit/source verification; the two actual Docker integration runs
were executed locally and have the separate evidence described above.

## 2026-10-29 — actual offline backup to fresh-boundary restore

Previous goal turn was progress: actual two-boundary local engine integration,
cleanup, pushed commit 14e8e2d and passing CI. Continued local/draft-only work;
production spending remains declined and no launch authorization was inferred
for resources outside that scope.

Added a synthetic offline backup/restore harness, bounded SDK object export/
import/readback, an actual restore engine script and 15 unit/fault tests. Engine
metadata, journal, worker state and configuration are copied only after checking
that its original container has exited. Original engine/store/network are removed
and inventories verified before constructing the restore boundary. A fresh store
imports both known 4 MiB objects, verifies full readback bytes, then a real engine
boots from the copied state without formatting or mounting original state.
Old files match original bytes; a new write matches both engine and independent
object-store reads. Both actual runs passed; final run has complete object-import
readback. All test containers/networks and temporary fixture credentials were
confirmed removed; unrelated services preserved. Full non-sensitive hashes,
private evidence paths, reproduction and limits are in marketplace-backup-smoke.md.

All **193 Python tests pass locally**, plus shell syntax, Python compilation,
provenance/attribution and whitespace checks. This reuses the existing binary;
no full Rust release rebuild, cold-cache recovery, FUSE, HA, production backup
service/policy, production subscription or buyer test is claimed.

AWS browser revalidation: the old numeric browser ID no longer consistently
identified Chrome after a session reset. Refreshed documented browser inventory,
selected the actual Chrome extension and read browser-troubleshooting guidance.
Creating a new work tab returned Group not found, and claiming/reading the
existing seller tab timed out. Enumeration is not authentication/product-state
evidence. No cookies/credentials were extracted, no alternate protocol bypass
was used, and no listing mutation was made. Last verified AWS product state
remains Staging, unrefreshed. No new product, ChangeSet, price, fulfillment URL,
public review or buyer-visible SaaS page is claimed.

Implementation `460e425763c3e6eb4e7ccaa8708ab1ca1c3f2a74` was pushed normally to
codex/marketplace-saas-integration. GitHub Actions run **40815445937** completed
with **success**, confirmed by `gh run watch --exit-status`:
https://github.com/Runix-lab/runix-fs/actions/runs/40815445937
This CI verifies source/unit checks; actual backup/restore was local and has the
separate runtime evidence above. It does not change Marketplace publication state.

## 2026-10-29 — PAYG update evidence and fresh pending-intent verification

Previous goal turn was progress: actual offline backup/fresh-boundary restore,
committed/pushed code 460e425 and successful CI. Continued the authorized local
and draft scope, without cloud spending, purchases or a public launch claim.

Obtained new authoritative evidence that changes the implementation path. Web
search could not render the official Concurrent Agreements workshop. Opened it
in the in-app browser, read its actual article and selected the PAYG tab. Task 2
skips the Contract GetEntitlements path; Task 3's usage panel explicitly defines
the License Updated - Manufacturer signal needed for PAYG, alongside the negative
license signal. This resolves the earlier uncertainty from the generic example.
Reference: https://catalog.workshops.aws/mpseller/en-US/saas/integration-for-concurrent-agreements
No tutorial stack, IAM change, email subscription, metering request or buyer
purchase was executed. Public documentation browsing does not establish seller
portal access or current product status.

Implemented PaygLicenseState: strict shared envelope/identity parsing, durable
monotone update evidence, immutable audit/replay checks shared with negatives,
and a fresh internal check for an existing organization-bound pending intent.
AgreementReader runs outside the DB lock; current agreement/time, binding and
negative stop guards are checked again before returning bounded evidence.
Negative tombstones always win, including an event committed during the AWS read.
Missing verification configuration or AWS errors never produce success. Pending
intents are not advanced, and no resources, access credentials or usage are made.
No guessed seller GetAgreementEntitlements call or legacy Contract PAYG check.

Added 27 tests covering malformed/foreign events, pre-registration updates,
repeat/cross-kind/changed-body replay, two licenses, event order, unauthorized
binding, current/future/elapsed agreements, clock bounds, SDK errors, concurrent
updates/stops, binding changes during reads, rollback and real process exit.
All **220 Python tests pass locally**, with provenance and whitespace checks.
Existing negative-reducer tests still pass. No Rust or engine change this turn.

This is a local integration component, not a deployed positive-license service.
Real EventBridge/SQS origin and IAM, missing-event reconciliation, IdP/browser
login, resource provisioning/revocation, source usage, hard quota, final metering,
production budget and buyer verification remain gates. The last confirmed AWS
product state remains Staging, unrefreshed. No new ChangeSet or public buyer URL.

Implementation commit `be8bc25dbfe59450d15b7c417c1314533d1ab2c5` was pushed
normally to codex/marketplace-saas-integration. GitHub Actions run **40817081688**
for that exact SHA completed with **success**:
https://github.com/Runix-lab/runix-fs/actions/runs/40817081688
Read-only workflow listing confirmed the completed status and matching SHA.
This is local/CI verification of synthetic event and SDK-model scenarios, not
real seller transport, paid activation, provisioning or Marketplace publication.

## 2026-10-29 — SDK event transport and real archive-replay semantics

Previous goal turn was progress: local PAYG update/check implementation, pushed
be8bc25 and successful CI. Continued local/draft-only scope. No AWS resource,
permission, policy, subscription, archive, replay or billing request was created.

Implemented SqsLifecycleWorker with actual SDK clients and a bounded CLI. It pins
seller/consumer role and us-east-1 identifiers, reads actual queue attributes and
rule/targets, checks the narrow raw-event route/send-policy/encryption/retention/
retry/DLQ profile before polling and again before accepting a message. Root,
foreign identity/queue/rule, broad sender policies and target input transforms
are refused. No new resource or policy write API is called. Configured resource
ARNs in tests are explicitly synthetic; no fabricated live configuration exists.

One received event is size/checksum/JSON validated and committed through the
real SQLite reducers before DeleteMessage. SDK failures are sanitized, invalid
messages/DB failures are not acknowledged, and a delete failure can safely
redeliver the same event with a new receipt handle. The CLI does not echo event
bodies, handles, responses or credential-like configuration fields. A successful
poll does not create a cluster, permit usage or mark the service ready.

Re-read current primary SQS/EventBridge/IAM docs and installed botocore models.
The classic event metadata page establishes the reserved source namespace;
no v2 custom-bus metadata assumption was substituted for it. The official archive
guide shows replay-name is added on archive replay. Updated canonical audit
hashing to ignore only that validated transport field while preserving all
business/envelope changes and all old stored hashes. Positive and negative
archive replays stay idempotent and never clear stops. Real AWS service-origin
and effective IAM validation remain outstanding; source strings alone never
establish a trusted producer.

Added 33 tests with actual botocore request/response models and SQLite. Final
complete suite: **253 passed locally**, plus provenance, Python compilation and
whitespace checks. The SDK rejected an initially empty paginated Targets fixture;
fixed the fixture to the real model shape before counting the test as passed.
Implementation and source references are in marketplace-event-worker.md.

No live SQS receive/delete, EventBridge event or deployed role is verified.
Actual route validation, monitoring/DLQ redrive, missed-event reconciliation,
production identity/login, resource provision/revoke, quotas/source usage,
final billing and buyer tests remain gates. Production budget is still declined.
Last confirmed AWS product status remains Staging, unrefreshed; no ChangeSet,
public review, fulfillment URL, configured price or buyer-visible service added.

Implementation `cc66245cd9041517ea28b4c9be3bf30c31bc63db` was pushed normally to
codex/marketplace-saas-integration. GitHub Actions run **40819754446** for that
exact SHA completed with **success**, confirmed from the workflow API listing:
https://github.com/Runix-lab/runix-fs/actions/runs/40819754446
This verifies source/unit checks. All AWS transport responses in these tests
remain Stubber fixtures; no actual live queue/origin or public service is proven.

## 2026-10-29 — real local OIDC code/PKCE foundation

Continued the user's local/draft-only scope; production budget remains declined.
No AWS resources, paid subscriptions, live metering, public endpoint or account
changes were made. Previous event worker CI was green at 40819754446.

Source discovery: public Router console actually shows username/password sign-in.
The separate private gateway deployment repository did not establish a reusable
OIDC issuer/client/JWKS. No proprietary gateway source, cookies or API keys were
copied into this Apache-licensed FS repository. The dirty website repository and
existing identity services were left untouched. Public official OIDC/Casdoor
references and actual fixture behavior informed this new implementation.

Implemented internal OIDC begin/complete with S256, nonce, browser correlation,
private durable state and committed single consumption before token exchange.
Provider/client/endpoints are fixed and bound to the database. Token HTTP uses
bounded direct TLS with no redirect or automatic retry; the explicit literal
loopback exception is only for synthetic local tests. A separate RS256 ID-token
verifier checks actual signatures, issuer, audience/authorized-party, nonce,
trusted time and optional code/access-token hashes. It does not turn provider
organization/admin claims into Runix permissions. Existing API access-token
validation stays strict and separate. No browser session or role is minted.

Added 30 tests for signatures/claims/header confusion, PKCE/correlation, cross-
browser denial, callback concurrency, transaction rollback, real process crash,
restart/replay, delayed/failed exchange, config pinning, credential redaction
and owned-fixture cleanup failures. All 283 Python tests pass locally, with
provenance, compilation and whitespace checks. One adversarial test initially
let the encoder strip its unsupported header; exact-wire signing now validates
the actual rejection instead of relying on encoder behavior.

Actual provider run (not a stub): fresh official cached Casdoor digest in
control-plane-oidc.md; synthetic credential-to-code API request, S256 token
exchange and actual 4096-bit RSA ID-token verification passed. A fresh code with
wrong PKCE and a redeemed code with its original correct verifier were refused;
local consumed callback replay was refused. Final evidence:
/var/folders/2x/cb5tfqrd52x2ddhb39yfn35w0000gn/T/runix-oidc-smoke-1qb8plq4/
Only metadata/results are recorded here. Passwords, codes, tokens, private keys,
client secrets and diagnostic logs stay outside Git. Fresh inventories confirmed
all owned containers/network removed and the secret env file deleted. No host
port was published. Two initial host-loopback probes failed and were cleaned;
the successful fixture uses its own isolated provider/client namespace instead.

Browser HTTP handoff, cookies/CSRF/logout, organization self-service, production
IdP configuration, provisioning/revocation, source usage/hard quota, missing-
event reconciliation, final billing and real buyer verification remain gates.
The existing Registry HTTPS issuer requirement has not been weakened for tests.
Latest confirmed product remains Staging (not refreshed); no new ChangeSet,
configured AWS price, review request or buyer-visible service was obtained.
