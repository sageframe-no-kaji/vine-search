# Container security review

The initial Debian 12 image was rejected after Trivy 0.76.0 reported 185 high/critical
package occurrences. The rebuilt Debian 13 image removes unnecessary Debian
Node/Pillow package dependencies and upgrades installed system packages. Its audit
reports 95 occurrences across 37 unique CVEs: 94 high and 1 critical. None of these
records contains a `FixedVersion` for Debian 13 at the scan capture; this does not
mean upstream fixes are unavailable. This is an open finding inventory, not a clean
scan or a general security certification.

`pip-audit` reports no known vulnerabilities in the locked application Python
environment. Trivy scans package metadata; it does not establish that every bundled
Chromium component is safe. The exact final image digest and repeat scan belong in
[release verification](release-verification.md).

## Disposition for private prerelease testing

The examined system-package findings are accepted for an operator-only private
prerelease with the boundaries below. Network access to the dashboard grants
application access: CSRF protection and login-viewer capabilities do not authenticate
the operator. Use loopback with an operator-controlled tunnel, or restrict the
Tailscale service to the operator through tailnet access rules as described in
[operations](operations.md#phone-and-private-network). A public-facing dashboard or
untrusted multi-user deployment is outside this disposition.

`VINE_SEARCH_ALLOWED_CLIENTS` adds a connection-peer IP/CIDR guard to every HTTP
route and the login-viewer WebSocket. Configure operator device addresses and
loopback health-check addresses for direct Tailscale deployment; the unset default
preserves installations whose access boundary is the loopback tunnel. The shipped
server ignores forwarding headers, while a reverse proxy must enforce operator
access itself because the application sees that proxy's peer address.

These findings remain documented rather than suppressed. Rebuild and re-audit when
Debian publishes fixes, and reconsider the disposition if the browser, desktop,
access boundary or enabled helper features change. A collector compromise can
expose its Amazon profile and shared application data despite the container controls.

- The scanner's critical `CVE-2026-6653` concerns libxml2 XML parsing. Debian explicitly
  classifies the Debian 13 issue as minor/no-DSA, while Trivy uses NVD's critical
  severity. The captured dynamic-linkage check places system libxml2 in Openbox's
  dependency closure and does not list it for Chromium, Xvfb or x11vnc. This does
  not inspect statically bundled browser XML code or prove absence of runtime
  loading. Openbox reads shipped configuration and themes, but its wider rendering
  dependency surface is not claimed unreachable. Debian's minor/no-DSA ruling is
  specific to this CVE and does not dispose of the other libxml2 findings.
  See the [Debian advisory](https://security-tracker.debian.org/tracker/CVE-2026-6653).
- X.Org, libX11, libXrender and libXtst findings concern display-client/server
  processing. Xvfb does not listen on TCP; the temporary desktop, x11vnc and
  websockify remain inside the collector. Only a same-origin, expiring capability
  reaches its proxy through the protected application routes. The single-screen
  Xvfb command also excludes the multi-screen trigger described for
  [CVE-2023-5574](https://security-tracker.debian.org/tracker/CVE-2023-5574).
  A compromised browser/display client remains a residual risk; this isolation
  is not a claim that the underlying libraries are patched.
- util-linux, ACL and systemd findings concern local privileged operations.
  Both application roles run as UID 1000 with all capabilities dropped,
  `no-new-privileges`, a read-only image and no host filesystem/docker-socket mount.
  No systemd-homed service or privileged mount helper is part of the application.
- CUPS server processing and the `tiffcrop` command are not application flows.
  There is no print daemon. TIFF findings also include a decoder denial of service,
  [CVE-2026-36849](https://security-tracker.debian.org/tracker/CVE-2026-36849), so the
  package is not dismissed solely because `tiffcrop` is unused. The image proxy
  accepts only JPEG, PNG, WebP and GIF response MIME types and limits response size;
  it copies bytes without decoding them. This check does not establish the actual
  file format or remove desktop rendering libraries from the residual surface.
- Debian Python 3.13 is used for the local websockify helper. The application and
  backup/restore use the image's separate CPython 3.12 runtime; `uv.lock` locks
  application packages, not that interpreter. The helper command does not enable
  TLS/auth plugins, urllib3 downloads, archive processing or HTML/XML parsing; its
  HTTP/WebSocket listener binds loopback and is temporary. Application restoration
  rejects symbolic and hard links and copies validated regular-file entries with
  `extractfile`, so it does not use the extraction-filter path in CVE-2026-82049.
- The application does parse Amazon HTML with BeautifulSoup's `html.parser`
  backend on CPython 3.12. Each complete document is fed once, rather than the
  repeated small-chunk feeding required by
  [CVE-2026-15308](https://security-tracker.debian.org/tracker/CVE-2026-15308).
  The Debian Python package inventory and `pip-audit` do not certify the separate
  interpreter's standard library.
- The ncurses finding concerns `infocmp`; the Perl finding concerns
  `Archive::Tar`. Neither is invoked by application requests, and there is no
  interactive public shell or general file-processing endpoint.

The intended access boundary, secret masking, CSRF/Origin checks, URL validation,
markup escaping and viewer expiry were exercised by independent tests. That review
and its limits are recorded in [QA review](qa-review.md). No actual Amazon credentials
were used during these probes.

## Open findings

Each row links the primary Debian record. Repeated binary packages from one source
package account for the difference between 37 CVEs and 95 package occurrences.

| CVE | Scanner severity | Installed packages |
| --- | --- | --- |
| [CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642) | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| [CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409) | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | HIGH | bsdutils, libblkid1, liblastlog2-2, libmount1, libsmartcols1, libuuid1, login, mount, util-linux |
| [CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | HIGH | libacl1 |
| [CVE-2026-34980](https://security-tracker.debian.org/tracker/CVE-2026-34980) | HIGH | libcups2t64 |
| [CVE-2026-55453](https://security-tracker.debian.org/tracker/CVE-2026-55453) | HIGH | libcups2t64 |
| [CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | HIGH | libncursesw6, libtinfo6, ncurses-base, ncurses-bin |
| [CVE-2026-15308](https://security-tracker.debian.org/tracker/CVE-2026-15308) | HIGH | libpython3.13-minimal, libpython3.13-stdlib, python3.13, python3.13-minimal |
| [CVE-2026-19445](https://security-tracker.debian.org/tracker/CVE-2026-19445) | HIGH | libpython3.13-minimal, libpython3.13-stdlib, python3.13, python3.13-minimal |
| [CVE-2026-19553](https://security-tracker.debian.org/tracker/CVE-2026-19553) | HIGH | libpython3.13-minimal, libpython3.13-stdlib, python3.13, python3.13-minimal |
| [CVE-2026-7210](https://security-tracker.debian.org/tracker/CVE-2026-7210) | HIGH | libpython3.13-minimal, libpython3.13-stdlib, python3.13, python3.13-minimal |
| [CVE-2026-82049](https://security-tracker.debian.org/tracker/CVE-2026-82049) | HIGH | libpython3.13-minimal, libpython3.13-stdlib, python3.13, python3.13-minimal |
| [CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | HIGH | libsystemd0, libudev1 |
| [CVE-2026-36849](https://security-tracker.debian.org/tracker/CVE-2026-36849) | HIGH | libtiff6 |
| [CVE-2026-52490](https://security-tracker.debian.org/tracker/CVE-2026-52490) | HIGH | libtiff6 |
| [CVE-2026-88806](https://security-tracker.debian.org/tracker/CVE-2026-88806) | HIGH | libx11-6, libx11-data, libx11-xcb1 |
| [CVE-2026-6653](https://security-tracker.debian.org/tracker/CVE-2026-6653) | CRITICAL | libxml2 |
| [CVE-2026-74860](https://security-tracker.debian.org/tracker/CVE-2026-74860) | HIGH | libxml2 |
| [CVE-2026-86138](https://security-tracker.debian.org/tracker/CVE-2026-86138) | HIGH | libxml2 |
| [CVE-2026-86139](https://security-tracker.debian.org/tracker/CVE-2026-86139) | HIGH | libxml2 |
| [CVE-2026-86140](https://security-tracker.debian.org/tracker/CVE-2026-86140) | HIGH | libxml2 |
| [CVE-2026-86142](https://security-tracker.debian.org/tracker/CVE-2026-86142) | HIGH | libxml2 |
| [CVE-2026-86143](https://security-tracker.debian.org/tracker/CVE-2026-86143) | HIGH | libxml2 |
| [CVE-2026-86144](https://security-tracker.debian.org/tracker/CVE-2026-86144) | HIGH | libxml2 |
| [CVE-2026-88807](https://security-tracker.debian.org/tracker/CVE-2026-88807) | HIGH | libxrender1 |
| [CVE-2026-94286](https://security-tracker.debian.org/tracker/CVE-2026-94286) | HIGH | libxtst6 |
| [CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | HIGH | perl-base |
| [CVE-2026-69249](https://security-tracker.debian.org/tracker/CVE-2026-69249) | HIGH | python3-cryptography |
| [CVE-2025-66471](https://security-tracker.debian.org/tracker/CVE-2025-66471) | HIGH | python3-urllib3 |
| [CVE-2026-97687](https://security-tracker.debian.org/tracker/CVE-2026-97687) | HIGH | python3-urllib3 |
| [CVE-2026-97689](https://security-tracker.debian.org/tracker/CVE-2026-97689) | HIGH | python3-urllib3 |
| [CVE-2023-5574](https://security-tracker.debian.org/tracker/CVE-2023-5574) | HIGH | xserver-common, xvfb |
| [CVE-2026-88812](https://security-tracker.debian.org/tracker/CVE-2026-88812) | HIGH | xserver-common, xvfb |
| [CVE-2026-93516](https://security-tracker.debian.org/tracker/CVE-2026-93516) | HIGH | xserver-common, xvfb |
| [CVE-2026-93521](https://security-tracker.debian.org/tracker/CVE-2026-93521) | HIGH | xserver-common, xvfb |
| [CVE-2026-93523](https://security-tracker.debian.org/tracker/CVE-2026-93523) | HIGH | xserver-common, xvfb |

## Independent disposition — 2026-10-20

Accept the examined package findings for the operator-only private prerelease;
this bounded review identified no package CVE requiring a source fix before that
testing. The review reconciled every CVE/package row against the Trivy JSON,
inspected the Dockerfile and Compose controls, traced login and viewer access
through the web and collector, and checked image-proxy, HTML-parser and archive
restore paths. Vendor records confirm the specific minor-issue classifications
and exploit prerequisites cited above; other findings remain open on their own
terms. No exploit execution, live Amazon session or deployment access-rule test
was performed by this review.

The operator-address refinement has 23 targeted checks covering exact addresses,
IPv4/IPv6 networks, IPv4-mapped IPv6, invalid startup configuration, HTTP and viewer
WebSocket denial, and forwarding-header spoof attempts. Two tests start the
shipped web command on an actual loopback socket, including with
`FORWARDED_ALLOW_IPS=*`, and verify that forwarding headers cannot replace the
connection peer. The complete suite passed 222 tests with 95.12% branch-aware
coverage after this change and the concurrent backup correction; this evidence
does not verify Docker address preservation or the deployment's actual device list.

The reviewed scan was captured at `2026-10-20T11:43:30-04:00` from the intermediate
`linux/arm64` image `vine-search:dependency-audit`, image ID
`sha256:54003a035d856957e3d288828f1238800368f53db5640f2db11541ecf8bceb7e`.
It contained exactly 95 package occurrences, 37 unique CVEs, 94 high findings and
one critical finding, with no populated `FixedVersion` fields. The 37 table rows
and their binary-package sets match that capture without omissions. Raw scan and
linkage records remain in ignored `data/`; this report records the relevant
nonprivate evidence.

This image ID is not evidence for the final published image or an `amd64` build.
Record the final digest and repeat audit for each distributed architecture in
[release verification](release-verification.md), and verify the actual private
access boundary before using a real account. Those delivery checks and the
separate Amazon authentication/collection gate remain open; accepting this
package disposition does not complete them.
