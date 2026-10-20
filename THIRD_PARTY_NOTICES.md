# Third-party notices

VineSearch application code is Copyright (c) 2026 Andrew Marcus and is distributed
under the [MIT License](LICENSE). Third-party components retain their own copyrights
and licenses. This document identifies those components and the locations of their
full notices; it does not replace or relicense them.

## Python runtime and packages

The image uses CPython 3.12, distributed under the Python Software Foundation license
and historical notices retained in `/usr/local/lib/python3.12/LICENSE.txt`.
[CPython source releases](https://www.python.org/downloads/source/) include the
corresponding source and license terms. The Python patch version is available with
`python --version`. The image also contains pip (MIT) and uv 0.9.5 (MIT OR Apache-2.0);
their license files remain under `/usr/local/lib/python3.12/site-packages`.

The runtime packages below are pinned by `uv.lock`. Package names identify the
upstream projects on [PyPI](https://pypi.org/), whose exact release pages provide
release files and upstream project links. The authoritative full notices, including bundled
code notices, are retained in each installed package's `.dist-info` directory under
`/opt/venv/lib/python3.12/site-packages`.

| License | Runtime packages |
| --- | --- |
| MIT | annotated-doc, annotated-types, anyio, beautifulsoup4, fastapi, h11, httptools, markdown-it-py, mdurl, pydantic, pydantic-core, pyee, PyYAML, rich, soupsieve, typer, typing-inspection, watchfiles |
| BSD-3-Clause | click, httpcore, httpx, idna, Jinja2, MarkupSafe, python-dotenv, starlette, uvicorn, websockets |
| BSD-2-Clause | Pygments |
| Apache-2.0 | opentelemetry-api, playwright, python-multipart |
| MPL-2.0 | certifi |
| ISC | shellingham |
| PSF-2.0 | typing-extensions |
| MIT and PSF-2.0 notices | greenlet |
| MIT and Apache-2.0 notices | uvloop |

Certifi's Mozilla-derived certificate bundle and MPL notice are retained in its
installed package. Its matching source release is available through
[certifi 2026.10.19 on PyPI](https://pypi.org/project/certifi/2026.10.19/#files).
Typer retains its bundled Click license; httptools retains the http-parser and llhttp
licenses. Playwright's Node runtime license, `NOTICE`, `ThirdPartyNotices.txt`, and
per-bundle `*.LICENSE` files remain under `playwright/driver`. Its matching sources
are available from [Playwright 1.64.0](https://github.com/microsoft/playwright/tree/v1.64.0)
and [Playwright Python 1.64.0](https://github.com/microsoft/playwright-python/tree/v1.64.0).

## Browser and video helper

Playwright 1.64.0 installs Chromium/Chrome for Testing and Chrome Headless Shell
156.0.8078.4 (Playwright build 1248), plus FFmpeg build 1013. The exact installation
metadata is in `playwright/driver/package/browsers.json` and is exported with the
release's third-party inventory.

Chromium's top-level license is BSD-style, with separately licensed third-party
components. The browser's `chrome://credits` page contains their notices.
The headless distribution retains `LICENSE.headless_shell`, and each browser
distribution retains its upstream `ABOUT` file under `/opt/playwright`.
Corresponding Chromium sources and dependency revisions are available at the
[156.0.8078.4 source tag](https://chromium.googlesource.com/chromium/src/+/156.0.8078.4)
(commit `f842f52ef39fd97b449eb27cff414bf05a98ddce`) and its `DEPS` file. Follow Chromium's
[Linux checkout instructions](https://chromium.googlesource.com/chromium/src/+/main/docs/linux/build_instructions.md)
with that tag to obtain the source dependencies.

The standalone FFmpeg helper identifies itself as `n7.0.1-playwright-build-1013`.
Its LGPL-2.1 text is retained at `/opt/playwright/ffmpeg-1013/COPYING.LGPLv2.1`.
The [FFmpeg 7.0.1 source release](https://ffmpeg.org/releases/ffmpeg-7.0.1.tar.xz)
contains the upstream sources. The installed binary's complete `-version` output,
including build configuration, is exported as `ffmpeg-build.txt`.
The application does not modify these browser or FFmpeg distributions.

## Login viewer and Debian system packages

The browser login viewer uses Debian's noVNC assets, websockify, x11vnc, Xvfb, and
Openbox. VineSearch adapts noVNC's HTML startup as described below; the other listed
package executables are unmodified. Debian's full
copyright notices and license texts are retained in `/usr/share/doc/<package>/copyright`
and `/usr/share/common-licenses`, including notices for system libraries and fonts.

| Component | Principal licenses and attribution |
| --- | --- |
| noVNC | MPL-2.0 core, Joel Martin and contributors; BSD-2-Clause HTML/styles and DES code; CC-BY-SA-3.0 images by Joel Martin; OFL-1.1 Orbitron font by Matt McInerney; MIT/Expat and Zlib notices for pako |
| websockify | LGPL-3.0 core, Joel Martin and contributors; Debian copyright file also identifies MPL-2.0, LGPL-2.0, BSD-2-Clause, and GPL-2.0-or-later portions |
| x11vnc | GPL-2.0-or-later, Karl J. Runge and contributors, with the recorded OpenSSL linking exception |
| Openbox | GPL-2.0-or-later; BSD-3-Clause Debian packaging and separately identified GPL-3.0-or-later theme assets |
| Xvfb | X.Org/MIT-style licenses and individual notices in the `xserver-xorg-core` copyright file |

noVNC is extracted from the Debian package without its unrelated recommended
applications. Its version is in `/usr/share/novnc/VERSION.debian`; source metadata
and the package checksum remain in `/usr/share/doc/novnc`. Its JavaScript source,
styles, and image assets are served from `/usr/share/novnc`, with their existing
notices retained. During the build,
[`docker/prepare-novnc.py`](docker/prepare-novnc.py) moves the inline startup module
verbatim into `vine-start.js` and changes the HTML to load that external file, so it
works with the application's Content Security Policy. It also creates empty
`defaults.json` and `mandatory.json` files when absent. The original Debian source,
the transformation script, and the resulting served source files are included in
the source export.

[Container package sources](docs/debian-packages.md) documents the exact inventory
and Debian source export. The export contains original source archives,
Debian changes/build instructions, copyright notices, and checksums. Package versions
may differ by image architecture or rebuild; the generated inventory identifies the
actual image contents.

## Chromium seccomp profile

`docker/seccomp-chromium.json` derives from Microsoft Playwright's Apache-2.0
[seccomp profile at ae935a43d9e376e4759548f6b3c6905c7b282333](https://github.com/microsoft/playwright/blob/ae935a43d9e376e4759548f6b3c6905c7b282333/utils/docker/seccomp_profile.json).
Playwright is Copyright (c) Microsoft Corporation. Its upstream notice also
identifies code derived from [Puppeteer](https://github.com/puppeteer/puppeteer),
available under the Apache 2.0 license.
The upstream file has SHA-256
`cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.
VineSearch adds `chroot` to the first syscall allow rule, changes that rule's comment
to explain the namespace sandbox, and reformats the JSON with two-space indentation.
These modifications are Copyright (c) 2026 Andrew Marcus. The upstream
[Apache License 2.0](docker/LICENSE.playwright)
applies to this derived file.

## Bundled application fonts

IBM Plex Sans, IBM Plex Mono, and DM Serif Display are redistributed unmodified
under the SIL Open Font License 1.1. Each font's original copyright, license, and
reserved-name notices are adjacent to the font in `src/vine_search/static/fonts`.
[Font sources and checksums](src/vine_search/static/fonts/SOURCES.md) identify the
upstream files. Packaging filenames are shortened; the font contents are unchanged.

## FFmpeg bundled library notices

The FFmpeg helper identifies libvpx 1.14.1 and zlib 1.3.1 in its embedded
version strings. Their matching sources are available from
[libvpx v1.14.1](https://github.com/webmproject/libvpx/tree/v1.14.1) and
[zlib v1.3.1](https://github.com/madler/zlib/tree/v1.3.1). Their upstream
notices follow.

### libvpx

```text
Copyright (c) 2010, The WebM Project authors. All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

  * Redistributions of source code must retain the above copyright
    notice, this list of conditions and the following disclaimer.

  * Redistributions in binary form must reproduce the above copyright
    notice, this list of conditions and the following disclaimer in
    the documentation and/or other materials provided with the
    distribution.

  * Neither the name of Google, nor the WebM Project, nor the names
    of its contributors may be used to endorse or promote products
    derived from this software without specific prior written
    permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

### zlib

```text
Copyright notice:

 (C) 1995-2022 Jean-loup Gailly and Mark Adler

  This software is provided 'as-is', without any express or implied
  warranty.  In no event will the authors be held liable for any damages
  arising from the use of this software.

  Permission is granted to anyone to use this software for any purpose,
  including commercial applications, and to alter it and redistribute it
  freely, subject to the following restrictions:

  1. The origin of this software must not be misrepresented; you must not
     claim that you wrote the original software. If you use this software
     in a product, an acknowledgment in the product documentation would be
     appreciated but is not required.
  2. Altered source versions must be plainly marked as such, and must not be
     misrepresented as being the original software.
  3. This notice may not be removed or altered from any source distribution.

  Jean-loup Gailly        Mark Adler
  jloup@gzip.org          madler@alumni.caltech.edu
```
