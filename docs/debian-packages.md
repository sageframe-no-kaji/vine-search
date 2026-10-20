# Container package sources

The release image contains separate third-party programs and libraries with their
own licenses. The image retains Debian copyright notices in `/usr/share/doc` and
license texts in `/usr/share/common-licenses`; Python distributions retain their
license files. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the
browser, fonts, Python packages, and modified seccomp profile.

## Delivered sources for 0.1.0

The source assets below accompany image index
`sha256:b06a0197838e672ffdfc7671a2d1ea94f4d761c7478f7bb2b9e976c28057c6e0`,
built from source revision `89dff199286117957cb91a5ac59930ca0b7b41c9`.
The ARM64 image uses 204 Debian source/version pairs. AMD64 uses those same pairs
plus `libpciaccess=0.17-3`, so AMD64 source access requires both archives.

| Asset | Coverage | SHA-256 |
| --- | --- | --- |
| [ARM64 base source bundle](https://github.com/sageframe-no-kaji/vine-search/releases/download/v0.1.0/vine-search-0.1.0-third-party-sources-arm64.tar.gz) ([checksum](https://github.com/sageframe-no-kaji/vine-search/releases/download/v0.1.0/vine-search-0.1.0-third-party-sources-arm64.tar.gz.sha256)) | All 204 shared Debian source/version pairs, ARM64 inventory and notices | `95c561b98f257320b9fabeea3aab46c7317ac0d361b4dd49859256d97055710b` |
| [AMD64 source supplement](https://github.com/sageframe-no-kaji/vine-search/releases/download/v0.1.0/vine-search-0.1.0-third-party-sources-amd64-supplement.tar.gz) ([checksum](https://github.com/sageframe-no-kaji/vine-search/releases/download/v0.1.0/vine-search-0.1.0-third-party-sources-amd64-supplement.tar.gz.sha256)) | Exact `libpciaccess=0.17-3` source plus AMD64 inventory and notices; requires the base bundle | `bfaac22a109b09d0c97c21242f62144a04164ddab85ed52113ff69a4524b1c6e` |

The base bundle's 204 source identities and 457 descriptor-listed files were
checked against their `.dsc` identities, sizes and SHA-256 values. The supplement's
three descriptor-listed files passed the same checks. Together the archives
cover all 205 source/version pairs in the published images; the supplement's
`source-coverage.json` records that combined result. Its original `status.json`
describes an inventory-only export and correctly does not claim standalone
source completeness.

Both platforms match the shared bundle's Python package versions, Playwright
browser metadata and adapted noVNC source. The supplement retains the AMD64 FFmpeg
configuration, whose differences are limited to ARM64 target/cross-compiler and
documentation flags. See [security review](security-review.md#published-artifacts--2026-10-20)
for the platform manifests and package scans. Publication of these sources is
separate from live Amazon acceptance.

## Generating an inventory and source bundle

Generate the exact inventory and Debian source archive for each image architecture
from that image, after the final build. Use its immutable image digest when preparing
a release. This disposable container has no application-data or session mounts.

```sh
mkdir -p data/third-party
docker run --rm --user 0 --entrypoint python \
  --mount "type=bind,src=$PWD/data/third-party,dst=/output" \
  ghcr.io/sageframe-no-kaji/vine-search@sha256:b06a0197838e672ffdfc7671a2d1ea94f4d761c7478f7bb2b9e976c28057c6e0 \
  /app/docker/third-party-sources.py --output /output --download
```

The script records every installed Debian binary's version and corresponding source
version, including separately extracted noVNC assets. It downloads the exact source
packages through authenticated Debian source indexes, including the original source
archives and Debian changes/build instructions. It copies installed copyright and
license notices, records Python and Playwright versions, and writes `SHA256SUMS`.
The adapted noVNC files are included as `novnc-installed-source`, together with
the build script that moves its inline startup module into a separate file.
It does not read application records, credentials, or browser profiles.

`status.json` must report `debian_sources_complete: true` before the Debian bundle
is published. Missing versions produce a nonzero exit status; do not substitute a
newer source version. Recover retired versions from
[Debian Snapshot](https://snapshot.debian.org/) using the exact source identities in
`debian-sources.tsv`. Snapshot supports historical Debian source indexes, including
the matching `debian-security` archive.

Publish the generated files as downloadable assets beside the matching GitHub
release and identify the image digest and architecture in its release notes.
For a large bundle, split the archive into assets below the hosting limit and
include the reconstruction command and checksums. Keep this source access available
alongside the image; an inventory or successful image build alone does not establish
that the source assets were uploaded. The export is a delivery mechanism for Debian
sources, not a written promise to supply source later.

To inspect notices without network downloads, omit `--download`. That mode explicitly
records `debian_sources_complete: false`.

## Comparing a final image

Run inventory-only export from the final image digest into a fresh directory, with
no application-data or session mounts. For another build of the same architecture,
compare `debian-packages.tsv`, `debian-sources.tsv`, `python-packages.json`, and
`playwright-browsers.json` against the source bundle. Also compare `ffmpeg-build.txt`
and the adapted `novnc-installed-source` tree when those components change.
The inventory-only status describes that inventory run; do not overwrite a completed
source bundle's download status with it.

Across architectures, compare the source package/version pairs in
`debian-sources.tsv`; binary package names and build suffixes can differ. Any source
pair present in the final image but absent from the bundle needs its exact source
download before distribution. Compare Python package names/versions and Playwright
browser revisions separately, and retain each architecture's binary inventory.
An application-only rebuild can reuse a matching third-party source bundle; identify
the actual release image digest and Git source tag in the release notes. A bundle's
`inventory_image_digest` identifies the image inspected for that inventory.

When repacking a bundle, regenerate `SHA256SUMS` for the changed files, create the
archive without host extended attributes, normalize archive ownership to root, and
publish an SHA-256 checksum for the archive itself. Keep the original source archives
and their Debian `.dsc` files intact; each `.dsc` records source-file sizes and hashes.
