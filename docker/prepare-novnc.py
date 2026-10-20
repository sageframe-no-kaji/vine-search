"""Externalize noVNC's module bootstrap for the application's strict CSP.

This build-time transformation preserves the upstream JavaScript verbatim.
The original noVNC sources remain available through the Debian source export.
"""

from pathlib import Path

root = Path("/usr/share/novnc")
page = root / "vnc.html"
html = page.read_text()
start = '<script type="module">'
end = "</script>"
if html.count(start) != 1:
    raise RuntimeError("Unexpected noVNC module bootstrap; review before building")
before, remaining = html.split(start, 1)
script, after = remaining.split(end, 1)
if 'import UI from "./app/ui.js";' not in script:
    raise RuntimeError("Unexpected noVNC startup module")
(root / "vine-start.js").write_text(
    "/* noVNC vnc.html bootstrap, moved verbatim by VineSearch.\n"
    " * Copyright (C) 2019 The noVNC authors.\n"
    " * SPDX-License-Identifier: BSD-2-Clause\n"
    " * Full terms: /usr/share/doc/novnc/copyright and /app/THIRD_PARTY_NOTICES.md.\n"
    " */\n" + script
)
page.write_text(before + '<script type="module" src="vine-start.js"></script>' + after)
for name in ("defaults.json", "mandatory.json"):
    configuration = root / name
    if not configuration.exists():
        configuration.write_text("{}\n")
