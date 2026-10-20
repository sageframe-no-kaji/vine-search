The collector uses Playwright's Chromium seccomp profile from
https://github.com/microsoft/playwright/blob/ae935a43d9e376e4759548f6b3c6905c7b282333/utils/docker/seccomp_profile.json
(Apache-2.0). Its extra user-namespace permissions allow the Chromium sandbox
inside a non-root container. It also permits `chroot`, which Chromium needs
inside its user namespace when all container capabilities are dropped.
No host VNC or collector port is published.

The on-demand viewer uses Debian's noVNC static assets (MPL-2.0) and websockify
(LGPL-3.0). noVNC assets and copyright text are extracted from the signed Debian
package in a separate build stage, so the runtime needs no extra Debian Node.js
or noVNC Python helper packages. Playwright includes its own Node.js runtime.
The noVNC package/source metadata is recorded under
`/usr/share/doc/novnc`. Package license texts are installed under `/usr/share/doc`
in the image. Xvfb, Openbox and x11vnc run only while a login session is active.
Openbox gives the server browser normal window sizing and keyboard focus.
The build moves noVNC's BSD-2-Clause HTML bootstrap verbatim into `vine-start.js`
using `prepare-novnc.py`, so the viewer works under the application's policy
against inline JavaScript. Empty optional settings files avoid startup errors.

The web container has the application-data volume but never the session volume.
The shared internal service credential belongs in the operator's private `.env`.
The application binds loopback by default; an operator may choose a private
interface with `VINE_SEARCH_BIND`, never a public unauthenticated interface.
