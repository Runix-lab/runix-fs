# Marketplace progress log

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
3. Keep model/prices/terms/fulfillment empty until approved and deliverable.
4. Continue beyond the SDK adapter into real identity, durable org/license
   binding, private provisioning and lifecycle handling. Unit tests are not
   evidence of deployment, end-to-end authentication, quota or storage delivery.
5. Prepare an explicit infrastructure budget and obtain approval before creating
   any resources. Real purchase tests need a buyer identity and spending cap.

No secret, runtime usage ledger, raw registration token or customer identity
material belongs in this log or a Git commit.
