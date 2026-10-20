# Container package sources

The release image contains separate third-party programs and libraries with their
own licenses. The image retains Debian copyright notices in `/usr/share/doc` and
license texts in `/usr/share/common-licenses`; Python distributions retain their
license files. See [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) for the
browser, fonts, Python packages, and modified seccomp profile.

Generate the exact inventory and Debian source archive for each image architecture
from that image, after the final build. Use its immutable image digest when preparing
a release. This disposable container has no application-data or session mounts.

```sh
mkdir -p data/third-party
docker run --rm --user 0 --entrypoint python \
  --mount "type=bind,src=$PWD/data/third-party,dst=/output" \
  ghcr.io/sageframe-no-kaji/vine-search:0.1.0 \
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
