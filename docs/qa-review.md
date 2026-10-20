# Independent MVP acceptance review

Reviewed 2026-10-20 against the version 0.1.0 acceptance criteria and [API contract](api-contract.md). All five reported interface findings are resolved. This verdict covers the verified corrections and inspected synthetic interface; live-account and release acceptance remain separate gates.

## Scope and evidence

This review combined source inspection, an isolated installation with synthetic data, real Chromium browser actions, HTTP/WebSocket boundary probes and a real loopback HTTP notification receiver. The reviewer opened all 20 captures covering five views at 1440, 768, 390 and 360 pixels, plus three connection/import/live-job state captures. Required widths and the named content were present; no missing or malformed capture was accepted. The screenshots show synthetic products and review records, not an Amazon account.

## Findings and resolution

All five corrections were independently scored against updated captures and the same behavioral probes. The original failure is retained below to make the evidence traceable.

| ID | Severity | Reproduction and consequence | Verified correction |
| --- | --- | --- | --- |
| QA-01 | P1 | All-history Discover shows products from RFY, AFA and search, while its footer reports only the first RFY run and says only that scope is represented. The displayed evidence cannot support the result set. | Resolved: the refreshed captures and actual DOM name RFY, AFA and search scopes separately; selected live-job results retain their exact query and truncated run. |
| QA-02 | P1 | With browser timezone America/New_York, stored order date `2026-09-26` renders as `Sep 25`. The same helper formats personal targets and observed deadlines. | Resolved: the New York browser and all four refreshed Review captures display September 26 for the stored September 26 date. |
| QA-03 | P2 | Fail the first bootstrap request, restore the service and click Try again. Discover returns, but settings save fails with the request-forgery error because bootstrap/CSRF was never restored. | Resolved: the same injected failure and Try again sequence now saves 40 minutes with no form error; initialization resets the prior polling interval. |
| QA-04 | P2 | Mark a review Submitted. The summary still shows zero submitted. With Not started selected, the changed record remains in that filtered list. | Resolved: the summary increments to one submitted and Not started shrinks from three rows to two with no incompatible row remaining. |
| QA-05 | P2 | Delete help and confirmation promise to remove tracker definitions; the implementation deliberately preserves them. | Resolved: help, confirmation and actual DOM text explicitly preserve tracker rules and settings. |

## Verified

The independent acceptance script passed 34 browser/API assertions after correction with no browser JavaScript errors. It verified local title search; browser-created tracker weights, exclusions, category restrictions, pause and deletion; preservation of observations; import preview and commit with private body/note/cookie fields stripped; markup rendered as text; review local progress remaining independent of observed Amazon status; settings persistence; queued live search excluding history and surviving reload; exact live-job membership including titles that do not repeat the query; truncated coverage; Activity reopening the captured job; cancellation; and actionable collector failure with saved history intact.

Targeted security probes rejected unsigned writes, mismatched Origin, cross-site Fetch Metadata, unexpected Host, unauthenticated viewer/lifecycle access and static traversal. Invalid product URLs with script schemes, deceptive hostnames, embedded credentials or alternate ports were rejected. Missing-capability and cross-origin WebSocket handshakes returned HTTP 403. Synthetic notification destination and bearer values were absent from settings, bootstrap, application export and outbox responses. These probes demonstrate the tested boundaries, not a general proof of security.

A real loopback HTTP receiver accepted a user-requested test while ordinary alerts were disabled. The request carried an idempotency key, the outbox recorded Sent, and the secret was absent from the returned outbox record. No external destination was contacted. A targeted native-dialog check also confirmed that Escape after an earlier confirmation preserved the edited setting; the suspected stale confirmation result was not reproduced.

The reviewer inspected the actual local font assets, URL validation and escaping paths, browser/session separation in Compose, protected viewer forwarding, image-host restriction, image-response MIME/size limits and no-redirect delivery behavior. The supplied images and layout preserve neutral backgrounds, near-square controls, responsive filter disclosure and separate review-status columns. Automated design checks reported type-size advisories; those checks were not rerun after correction.

## Container evidence and remaining verification

Actual Amazon authentication, Vine membership detection, live queue/search pagination, live review synchronization and reconnect persistence remain blocked by the absence of an authorized dedicated session. The existing live-verification record reports that block. Synthetic results and screenshots do not establish those outcomes.

The served-login exercise completed inside the local Linux arm64 image. This reviewer inspected the verifier source, successful JSON output, tested-image identity and actual noVNC screenshot. The test used a disposable account-free synthetic login page; it explicitly asserted the text typed through the viewer, completion by Enter, the application iframe closing, exclusive browser ownership, private session-cookie persistence and subsequent headless reuse, reconnect cancellation, expiry revocation and denial without a viewer capability. No client JavaScript errors were recorded. The image identity was `sha256:e595598404709c2a1e51b285619c2e518cf04246d2f356ef7dbbf8ceba8264e1` on `linux/arm64`. This establishes local container transport and lifecycle evidence; it does not establish actual Amazon authentication, physical-phone usability or a fresh public-image pull.

Physical-phone operation, real external notification delivery, a fresh public-image install, remote CI, repository publication and release rendering were not run by this reviewer. Those categories must retain their own evidence in the release verification matrix. Simulated mobile viewport captures are not physical-phone evidence.

## Recorded outcome

All five findings were resolved with no introduced material regression observed in the inspected behavior. Computed browser values confirm ground `rgb(244, 245, 247)` and DM Serif Display headings at weight 400. The observations in this review use synthetic records and retain the evidence limits stated above.
