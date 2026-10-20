#!/usr/bin/env python3
"""Export image notices, exact package inventory, and Debian source archives.

Run in a disposable copy of the release image, never in a running application
container. --download requires root and network access; inventory alone does not.
The output deliberately reads no application databases or browser profiles.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(arguments: list[str], cwd: Path | None = None) -> str:
    return subprocess.check_output(arguments, cwd=cwd, text=True, stderr=subprocess.STDOUT)


def retain(path: Path, output: Path) -> None:
    if path.is_file():
        target = output / "licenses" / path.relative_to("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def inventory(output: Path) -> list[tuple[str, str]]:
    fields = (
        "${binary:Package}\t${Version}\t${source:Package}\t${source:Version}\t${Architecture}\n"
    )
    rows = [line.split("\t") for line in run(["dpkg-query", "-W", "-f=" + fields]).splitlines()]
    novnc = Path("/usr/share/doc/novnc")
    novnc_version = Path("/usr/share/novnc/VERSION.debian")
    if not any(row[0] == "novnc" for row in rows) and novnc_version.exists():
        version = novnc_version.read_text().strip()
        retain(novnc_version, output)
        source_name, source_version = "novnc", version
        if (novnc / "SOURCE.debian").exists():
            metadata = (novnc / "SOURCE.debian").read_text()
            match = re.search(r"^Source: (\S+)(?: \(([^)]+)\))?", metadata, re.MULTILINE)
            if match:
                source_name = match[1]
                source_version = match[2] or version
        rows.append(["novnc", version, source_name, source_version, "all (extracted assets)"])
    rows.sort()
    header = "binary_package\tbinary_version\tsource_package\tsource_version\tarchitecture\n"
    (output / "debian-packages.tsv").write_text(
        header + "".join("\t".join(row) + "\n" for row in rows)
    )
    sources = sorted({(row[2], row[3]) for row in rows})
    (output / "debian-sources.tsv").write_text(
        "source_package\tsource_version\n" + "".join(f"{n}\t{v}\n" for n, v in sources)
    )
    for base in (Path("/usr/share/doc"), Path("/usr/share/common-licenses")):
        for path in base.rglob("*"):
            if base.name == "common-licenses" or path.name in {
                "copyright",
                "SOURCE.debian",
                "VERSION.debian",
                "package.sha256",
            }:
                retain(path, output)
    python_rows = []
    search_paths = sorted(Path("/opt/venv/lib").glob("python*/site-packages"))
    search_paths += sorted(Path("/usr/local/lib").glob("python*/site-packages"))
    for dist in importlib.metadata.distributions(path=[str(p) for p in search_paths]):
        python_rows.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.version,
                "license_expression": dist.metadata.get("License-Expression"),
                "license": dist.metadata.get("License"),
                "project_urls": dist.metadata.get_all("Project-URL") or [],
            }
        )
        for relative in dist.files or []:
            if any(word in str(relative).lower() for word in ("license", "notice", "copying")):
                retain(Path(dist.locate_file(relative)), output)
    (output / "python-packages.json").write_text(
        json.dumps(sorted(python_rows, key=lambda row: str(row["name"]).lower()), indent=2) + "\n"
    )
    for pattern in ("/usr/local/lib/python*/LICENSE.txt", "/app/src/vine_search/static/fonts/*"):
        for path in Path("/").glob(pattern.removeprefix("/")):
            if path.suffix in {".txt", ".md"}:
                retain(path, output)
    for path in Path("/opt/playwright").rglob("*"):
        if any(word in path.name.lower() for word in ("license", "copying", "about")):
            retain(path, output)
    browser_metadata = list(
        Path("/opt/venv/lib").glob("python*/site-packages/playwright/driver/package/browsers.json")
    )
    if browser_metadata:
        shutil.copyfile(browser_metadata[0], output / "playwright-browsers.json")
    for executable in Path("/opt/playwright").glob("ffmpeg-*/ffmpeg-linux"):
        (output / "ffmpeg-build.txt").write_text(run([str(executable), "-version"]))
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
        retain(Path("/app") / name, output)
    retain(Path("/app/docker/LICENSE.playwright"), output)
    if Path("/usr/share/novnc").is_dir():
        shutil.copytree("/usr/share/novnc", output / "novnc-installed-source", dirs_exist_ok=True)
    build_script = Path("/app/docker/prepare-novnc.py")
    if build_script.is_file():
        (output / "build-scripts").mkdir(exist_ok=True)
        shutil.copyfile(build_script, output / "build-scripts" / build_script.name)
    shutil.copyfile("/etc/os-release", output / "os-release")
    return sources


def download_sources(sources: list[tuple[str, str]], output: Path) -> list[str]:
    """Use authenticated apt source indexes without altering system apt settings."""
    failures = []
    with tempfile.TemporaryDirectory(prefix="vine-source-index-") as temporary:
        config = Path(temporary)
        parts = config / "sources.list.d"
        parts.mkdir()
        for original in Path("/etc/apt/sources.list.d").glob("*.sources"):
            text = re.sub(r"^Types:.*$", "Types: deb-src", original.read_text(), flags=re.MULTILINE)
            (parts / original.name).write_text(text)
        if not list(parts.glob("*.sources")):
            raise RuntimeError("No deb822 apt source configuration found")
        lists = config / "lists"
        (lists / "partial").mkdir(parents=True)
        empty_list = config / "sources.list"
        empty_list.touch()
        options = [
            "-o",
            f"Dir::Etc::sourcelist={empty_list}",
            "-o",
            f"Dir::Etc::sourceparts={parts}",
            "-o",
            f"Dir::State::lists={lists}",
            "-o",
            "APT::Sandbox::User=root",
            "-o",
            "Acquire::Retries=3",
        ]
        print("Fetching signed Debian source indexes", flush=True)
        run(["apt-get", *options, "update"])
        for number, (name, version) in enumerate(sources, 1):
            target = output / "debian-source" / name / version.replace(":", "%3A")
            target.mkdir(parents=True, exist_ok=True)
            print(f"[{number}/{len(sources)}] {name}={version}", flush=True)
            try:
                log = run(
                    [
                        "apt-get",
                        *options,
                        "source",
                        "--download-only",
                        "--only-source",
                        f"{name}={version}",
                    ],
                    cwd=target,
                )
                (target / "download.log").write_text(log)
            except subprocess.CalledProcessError as error:
                (target / "download.log").write_text(error.output)
                failures.append(f"{name}={version}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--download", action="store_true", help="Download every exact Debian source"
    )
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # A failed retry must never leave a previous successful status behind.
    (output / "status.json").write_text(
        json.dumps({"debian_sources_complete": False, "state": "exporting"}, indent=2) + "\n"
    )
    sources = inventory(output)
    failures = download_sources(sources, output) if args.download else []
    (output / "status.json").write_text(
        json.dumps(
            {
                "debian_source_packages": len(sources),
                "download_requested": args.download,
                "debian_sources_complete": args.download and not failures,
                "failed_sources": failures,
                "scope": (
                    "Debian archives and installed notices; "
                    "browser/Python sources use notices links"
                ),
            },
            indent=2,
        )
        + "\n"
    )
    checksums = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            with path.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            checksums.append(f"{digest}  {path.relative_to(output)}\n")
    (output / "SHA256SUMS").write_text("".join(checksums))
    if failures:
        print("Missing exact source versions: " + ", ".join(failures), file=sys.stderr)
        return 1
    print(f"Exported {len(sources)} Debian source identities to {output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
