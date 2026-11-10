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
# noVNC 1.6 has no browser clipboard sync, so Ctrl/Cmd+V would paste the remote
# (empty) clipboard. Read the local clipboard instead and type it as keystrokes,
# which also works in password fields. Line breaks are dropped: never auto-submit.
(root / "vine-paste.js").write_text("""import UI from "./app/ui.js";
import keysyms from "./core/input/keysymdef.js";

const MODIFIERS = [0xffe3, 0xffe4, 0xffe7, 0xffe8, 0xffe9, 0xffea, 0xffeb, 0xffec];
window.addEventListener("keydown", async (event) => {
    if (!(event.ctrlKey || event.metaKey) || event.key.toLowerCase() !== "v") { return; }
    if (!UI.rfb || event.target.id === "noVNC_clipboard_text") { return; }
    event.preventDefault();
    event.stopImmediatePropagation();
    let text;
    try { text = await navigator.clipboard.readText(); } catch { return; }
    MODIFIERS.forEach((keysym) => UI.rfb.sendKey(keysym, null, false));
    for (const character of text.slice(0, 1000)) {
        const keysym = /[\\r\\n]/.test(character) ? 0 : keysyms.lookup(character.codePointAt(0));
        if (keysym) { UI.rfb.sendKey(keysym, null); }
    }
}, true);
""")
page.write_text(
    before
    + '<script type="module" src="vine-start.js"></script>'
    + '<script type="module" src="vine-paste.js"></script>'
    + after
)
for name in ("defaults.json", "mandatory.json"):
    configuration = root / name
    if not configuration.exists():
        configuration.write_text("{}\n")
