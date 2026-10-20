#!/usr/bin/env python3
"""Verify a supplied release image using fresh Compose volumes and synthetic records.

Run with host Python 3.11+ and Docker Compose; no Python packages are required.
The image must already have been pulled. Anonymous registry-pull evidence is a
separate check; this script records exactly which locally available image ran.

Example (use an unpacked release-assets directory, never a source checkout):
  python3 docker/verify-install.py --directory /tmp/vine-release \
    --image ghcr.io/sageframe-no-kaji/vine-search:0.1.0 --port 18765

The two randomly named projects are removed without --volumes on completion.
Their volumes and private backup remain available for inspection or recovery.
The JSON report never contains CSRF tokens, service keys, inventory or sessions.
"""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import tarfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request, build_opener

Json = dict[str, Any]


class VerificationError(Exception):
    """An actionable failure safe to include in a public verification report."""


def require(condition: object, message: str) -> None:
    if not condition:
        raise VerificationError(message)


class Dashboard:
    def __init__(self, port: int):
        self.origin = f"http://127.0.0.1:{port}"
        self.opener = build_opener(
            ProxyHandler({}), HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.token = ""
        self.timings: list[float] = []

    def request(
        self,
        path: str,
        method: str = "GET",
        data: Json | None = None,
        *,
        expected: int = 200,
        signed: bool = True,
    ) -> Any:
        headers = {"Accept": "application/json"}
        if method != "GET":
            headers.update({"Content-Type": "application/json", "Origin": self.origin})
            if signed:
                headers["X-CSRF-Token"] = self.token
                headers["Sec-Fetch-Site"] = "same-origin"
        request = Request(
            self.origin + path,
            data=json.dumps(data or {}).encode() if method != "GET" else None,
            headers=headers,
            method=method,
        )
        started = time.monotonic()
        try:
            try:
                response = self.opener.open(request, timeout=8)
            except HTTPError as error:
                response = error
            with response:
                status = response.status
                payload = response.read(2_000_001)
            require(
                status == expected, f"{method} {path} returned HTTP {status}; expected {expected}."
            )
            require(len(payload) <= 2_000_000, f"{path} exceeded the bounded response size.")
            return json.loads(payload)
        except (URLError, TimeoutError, OSError) as error:
            raise VerificationError(
                f"{method} {path} could not reach the local dashboard."
            ) from error
        except json.JSONDecodeError as error:
            raise VerificationError(f"{method} {path} did not return valid JSON.") from error
        finally:
            self.timings.append(round((time.monotonic() - started) * 1000, 2))

    def bootstrap(self) -> Json:
        result: Json = self.request("/api/bootstrap")
        token = result.get("csrf_token")
        require(isinstance(token, str) and bool(token), "Bootstrap did not issue a CSRF token.")
        self.token = token
        return result


class InstallVerifier:
    def __init__(self, args: argparse.Namespace):
        self.directory = args.directory.expanduser().resolve()
        self.image = args.image
        self.port = args.port
        self.timeout = args.timeout
        self.with_login = args.with_login
        suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)
        self.original = "vsverify-" + suffix
        self.restored = self.original + "-restored"
        self.private_dir = self.directory / ".verify-install" / suffix
        self.report_path = (
            args.report.expanduser().resolve()
            if args.report
            else (self.private_dir / "report.json")
        )
        self.archive = self.private_dir / "recovery.tgz"
        self.marker = secrets.token_urlsafe(32)
        self.delivery_secret = secrets.token_urlsafe(32)
        self.destination = "https://example.invalid/synthetic-install-destination"
        self.dashboard = Dashboard(self.port)
        excluded = {
            "COMPOSE_FILE",
            "COMPOSE_PROJECT_NAME",
            "COMPOSE_PROFILES",
            "COMPOSE_ENV_FILES",
            "COMPOSE_DISABLE_ENV_FILE",
        }
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key not in excluded and not key.startswith("VINE_SEARCH_")
        }
        self.environment.update(
            {
                "VINE_SEARCH_IMAGE": self.image,
                "VINE_SEARCH_PORT": str(self.port),
                "VINE_SEARCH_BIND": "127.0.0.1",
                "VINE_SEARCH_ALLOWED_HOSTS": "localhost,127.0.0.1,::1",
            }
        )
        self.projects_started: set[str] = set()
        self.volumes: dict[str, dict[str, str]] = {}
        self.fixture: Json = {}
        self.report: Json = {
            "mode": "fresh-release-image-install-recovery",
            "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "status": "running",
            "requested_image": self.image,
            "original_project": self.original,
            "restored_project": self.restored,
            "checks": [],
            "resource_samples": [],
            "evidence_limits": [
                "Synthetic records and a synthetic private marker; no Amazon credentials used.",
                "No live Amazon, physical-phone or external-notification delivery claim.",
                "Registry anonymity is verified separately; "
                "this script uses an already-pulled image.",
            ],
        }

    def command(
        self,
        arguments: list[str],
        *,
        label: str,
        stdin: str | None = None,
        timeout: int | None = None,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = subprocess.run(
                arguments,
                cwd=self.directory,
                env=self.environment,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout or self.timeout,
                check=False,
            )
        except FileNotFoundError as error:
            raise VerificationError(f"{label}: Docker CLI is unavailable on this host.") from error
        except subprocess.TimeoutExpired as error:
            raise VerificationError(
                f"{label}: exceeded {timeout or self.timeout} seconds; "
                "inspect the named test project."
            ) from error
        if result.returncode and not allow_failure:
            # Docker inspect/config and application output can contain private values.
            # Keep raw output out of both the console and persisted report.
            raise VerificationError(
                f"{label}: command exited {result.returncode}; inspect the named test project "
                "locally. Confirm the supplied image and documented command are available."
            )
        return result

    def compose(self, project: str, *arguments: str, label: str, **kwargs: Any) -> str:
        result = self.command(
            [
                "docker",
                "compose",
                "--project-directory",
                str(self.directory),
                "--env-file",
                str(self.directory / ".env"),
                "-f",
                str(self.directory / "compose.yaml"),
                "-p",
                project,
                *arguments,
            ],
            label=label,
            **kwargs,
        )
        return result.stdout

    def step(self, name: str, action: Callable[[], None]) -> None:
        started = time.monotonic()
        print(f"Checking {name}...", flush=True)
        try:
            action()
        except Exception:
            self.report["checks"].append(
                {
                    "name": name,
                    "status": "failed",
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                }
            )
            raise
        self.report["checks"].append(
            {
                "name": name,
                "status": "pass",
                "elapsed_seconds": round(time.monotonic() - started, 2),
            }
        )

    def preflight(self) -> None:
        require(
            self.directory.is_dir(), "--directory must be an unpacked release-assets directory."
        )
        require((self.directory / "compose.yaml").is_file(), "Release assets lack compose.yaml.")
        require(
            (self.directory / "docker/seccomp-chromium.json").is_file(),
            "Release assets lack docker/seccomp-chromium.json.",
        )
        require(
            not (self.directory / ".env").exists(),
            "Fresh-install verification requires a directory without an existing .env.",
        )
        require(
            not (self.directory / "src/vine_search").exists(),
            "Use unpacked release assets, not a developer source checkout.",
        )
        require(
            not (self.directory / "data").exists(),
            "Fresh-install verification refuses a directory with existing runtime data.",
        )
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", self.port))
            except OSError as error:
                raise VerificationError(
                    "Requested loopback port is in use; choose a free --port."
                ) from error
        self.command(["docker", "compose", "version"], label="Docker Compose prerequisite")
        image = self.command(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .Id}}\n{{json .RepoDigests}}\n{{json .Os}}\n{{json .Architecture}}",
                self.image,
            ],
            label="Inspect the already-pulled release image",
        ).stdout.splitlines()
        require(len(image) == 4, "Image identity inspection returned an unexpected format.")
        self.report["image"] = {
            "id": json.loads(image[0]),
            "repo_digests": json.loads(image[1]),
            "os": json.loads(image[2]),
            "architecture": json.loads(image[3]),
        }
        require(self.report["image"]["os"] == "linux", "The application requires a Linux image.")
        for project in (self.original, self.restored):
            existing = self.command(
                [
                    "docker",
                    "volume",
                    "ls",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{.Name}}",
                ],
                label="Check fresh project volumes",
            ).stdout.strip()
            require(
                not existing, "Generated test project already has volumes; rerun for a new name."
            )
        self.private_dir.mkdir(parents=True, mode=0o700)
        self.private_dir.chmod(0o700)

    def setup(self) -> None:
        self.command(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={self.directory},dst=/install",
                self.image,
                "setup",
                "--directory",
                "/install",
            ],
            label="Documented image setup --directory /install",
        )
        env_file = self.directory / ".env"
        require(
            env_file.is_file(), "Image setup did not create .env in the mounted install directory."
        )
        require(
            stat.S_IMODE(env_file.stat().st_mode) == 0o600, "Setup .env permissions must be 0600."
        )
        first_digest = hashlib.sha256(env_file.read_bytes()).digest()
        self.command(
            [
                "docker",
                "run",
                "--rm",
                "--pull",
                "never",
                "--user",
                f"{os.getuid()}:{os.getgid()}",
                "--mount",
                f"type=bind,src={self.directory},dst=/install",
                self.image,
                "setup",
                "--directory",
                "/install",
            ],
            label="Repeat setup preserves existing configuration",
        )
        require(
            hashlib.sha256(env_file.read_bytes()).digest() == first_digest,
            "Repeated setup changed the existing private configuration.",
        )
        self.compose(
            self.original, "config", "--quiet", label="Validate release Compose configuration"
        )

    def start(self, project: str) -> None:
        self.projects_started.add(project)
        self.compose(
            project,
            "up",
            "-d",
            "--no-build",
            "--pull",
            "never",
            "--wait",
            "--wait-timeout",
            str(self.timeout),
            label=f"Start {'restored' if project == self.restored else 'fresh'} release project",
            timeout=self.timeout + 30,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                health = self.dashboard.request("/health")
                if health.get("status") == "ok":
                    self.report["application_version"] = health.get("version")
                    self.dashboard.bootstrap()
                    return
            except VerificationError:
                pass
            time.sleep(0.5)
        raise VerificationError(
            "Compose started, but the local application health never became ready."
        )

    def container(self, project: str, service: str) -> str:
        identity = self.compose(
            project, "ps", "-q", service, label=f"Find {service} test container"
        ).strip()
        require(
            bool(identity) and "\n" not in identity, f"Expected exactly one {service} container."
        )
        return identity

    def inspect_mounts(self, project: str) -> None:
        role_volumes: dict[str, dict[str, str]] = {}
        for service in ("web", "collector"):
            identity = self.container(project, service)
            actual_image = self.command(
                ["docker", "inspect", "--format", "{{.Image}}", identity],
                label=f"Verify running {service} image identity",
            ).stdout.strip()
            require(
                actual_image == self.report["image"]["id"],
                f"The running {service} role differs from the inspected release image.",
            )
            mounts = json.loads(
                self.command(
                    ["docker", "inspect", "--format", "{{json .Mounts}}", identity],
                    label=f"Inspect {service} volume boundary",
                ).stdout
            )
            require(
                not any(mount["Type"] == "bind" for mount in mounts),
                f"The running {service} role has a host bind mount; "
                "release services need no source mount.",
            )
            role_volumes[service] = {
                mount["Destination"]: mount["Name"] for mount in mounts if mount["Type"] == "volume"
            }
            require(
                "/data" in role_volumes[service], f"{service} has no named application-data volume."
            )
            if service == "web":
                require(
                    not any(
                        path == "/session" or path.startswith("/session/")
                        for path in role_volumes[service]
                    ),
                    "The web role can access the private session volume.",
                )
            else:
                require(
                    "/session" in role_volumes[service],
                    "Collector lacks its private session volume.",
                )
        require(
            role_volumes["web"]["/data"] == role_volumes["collector"]["/data"],
            "Web and collector do not share the same application-data volume.",
        )
        self.volumes[project] = {
            "data": role_volumes["web"]["/data"],
            "session": role_volumes["collector"]["/session"],
        }
        if project == self.restored:
            require(
                set(self.volumes[self.original].values()).isdisjoint(
                    self.volumes[project].values()
                ),
                "Restored installation reused an original volume.",
            )

    def exercise_api(self) -> None:
        api = self.dashboard
        settings = api.request(
            "/api/settings",
            "PATCH",
            {
                "collection_enabled": False,
                "review_sync_enabled": False,
                "collection_interval_minutes": 35,
                "page_budget": 3,
                "image_mode": "hidden",
                "notifications_enabled": False,
                "notification_url": self.destination,
                "notification_secret": self.delivery_secret,
            },
        )
        require(settings["collection_interval_minutes"] == 35, "Settings write did not persist.")
        require(
            settings["notification_url"] == settings["notification_secret"] == "***",
            "Settings returned a private notification destination or token.",
        )
        api.request(
            "/api/settings",
            "PATCH",
            {"collection_interval_minutes": 99},
            expected=403,
            signed=False,
        )
        tracker = api.request(
            "/api/trackers",
            "POST",
            {
                "name": "Synthetic installer recovery tracker",
                "query": "synthetic fixture switch",
                "phrases": ["fixture switch"],
                "exclusions": ["fixture cover"],
                "phrase_weight": 77,
                "notify": False,
                "schedule_enabled": False,
            },
            expected=201,
        )
        self.fixture["tracker_id"] = tracker["id"]
        records = [
            {
                "external_id": "synthetic-install-recovery-order",
                "asin": "B000000123",
                "title": "Synthetic installer recovery switch",
                "variant": "Fixture only",
                "order_date": "2026-01-15",
                "observed_status": "Awaiting Review",
                "rating": 4,
                "body": "SYNTHETIC_PRIVATE_BODY_MUST_BE_DROPPED",
                "notes": "SYNTHETIC_PRIVATE_NOTE_MUST_BE_DROPPED",
                "credentials": "SYNTHETIC_PRIVATE_AUTH_MUST_BE_DROPPED",
            }
        ]
        preview = api.request("/api/reviews/import/preview", "POST", {"records": records})
        require(
            preview["accepted"] == 1 and not preview["rejected"],
            "Valid synthetic review metadata was rejected by import preview.",
        )
        require(
            {"body", "notes", "credentials"} <= set(preview["ignored_fields"]),
            "Import preview did not reject private freeform/authentication fields.",
        )
        require(
            "SYNTHETIC_PRIVATE_" not in json.dumps(preview["records"]),
            "Import preview retained private freeform/authentication content.",
        )
        committed = api.request(
            "/api/reviews/import",
            "POST",
            {
                "records": records,
                "preview_hash": preview["preview_hash"],
            },
        )
        require(
            committed["imported"] == 1, "Synthetic review import did not create exactly one record."
        )
        reviews = api.request("/api/reviews")
        require(reviews["total"] == 1, "Fresh installation contains unexpected review records.")
        self.fixture["review_id"] = reviews["items"][0]["id"]
        progress = api.request(
            f"/api/reviews/{self.fixture['review_id']}", "PATCH", {"local_progress": "in_progress"}
        )
        require(
            progress["observed_status"] == "Awaiting Review",
            "Local review progress changed the observed Amazon status.",
        )
        job = api.request(
            "/api/jobs",
            "POST",
            {
                "kind": "search",
                "query": "synthetic queued recovery search",
                "tracker_id": self.fixture["tracker_id"],
            },
            expected=202,
        )
        require(job["status"] == "queued", "Unauthenticated synthetic job did not remain queued.")
        self.fixture["job_id"] = job["id"]
        exported = json.dumps(api.request("/api/export"))
        require(
            self.delivery_secret not in exported and self.destination not in exported,
            "Application export revealed a configured destination or token.",
        )
        require(
            "SYNTHETIC_PRIVATE_" not in exported,
            "Application export retained excluded review fields.",
        )
        self.verify_state()

    def write_marker(self) -> None:
        self.compose(
            self.original,
            "exec",
            "-T",
            "collector",
            "python",
            "-c",
            "import pathlib,sys; p=pathlib.Path('/session/verify-install-marker'); "
            "p.write_text(sys.stdin.read()); p.chmod(0o600)",
            label="Write account-free private session marker",
            stdin=self.marker,
        )
        self.compose(
            self.original,
            "exec",
            "-T",
            "web",
            "python",
            "-c",
            "from pathlib import Path; "
            "assert not Path('/session/verify-install-marker').exists(), 'Private marker exposed'",
            label="Assert web cannot read collector session marker",
        )

    def verify_marker(self, project: str) -> None:
        digest = hashlib.sha256(self.marker.encode()).hexdigest()
        output = self.compose(
            project,
            "exec",
            "-T",
            "collector",
            "python",
            "-c",
            "import hashlib,pathlib; p=pathlib.Path('/session/verify-install-marker'); "
            "print(hashlib.sha256(p.read_bytes()).hexdigest()); "
            "assert p.stat().st_mode & 0o777 == 0o600",
            label="Verify private marker preservation without exposing its content",
        )
        require(output.strip() == digest, "Private session marker changed or was not restored.")

    def verify_state(self) -> None:
        api = self.dashboard
        api.bootstrap()
        settings = api.request("/api/settings")
        require(
            settings["collection_interval_minutes"] == 35 and settings["page_budget"] == 3,
            "Persistent collection settings changed across lifecycle operations.",
        )
        require(
            settings["collection_enabled"] is False and settings["image_mode"] == "hidden",
            "Persistent pause/image settings changed across lifecycle operations.",
        )
        require(
            settings["notification_url"] == settings["notification_secret"] == "***",
            "Stored notification configuration was lost or exposed.",
        )
        trackers = api.request("/api/trackers")
        matching = [item for item in trackers if item["id"] == self.fixture["tracker_id"]]
        require(
            len(matching) == 1 and matching[0]["phrase_weight"] == 77,
            "Saved tracker rules changed or disappeared.",
        )
        reviews = api.request("/api/reviews")
        matching = [item for item in reviews["items"] if item["id"] == self.fixture["review_id"]]
        require(
            len(matching) == 1 and matching[0]["local_progress"] == "in_progress",
            "Review record or its local progress did not survive.",
        )
        require(
            matching[0]["observed_status"] == "Awaiting Review",
            "Observed review status changed during recovery.",
        )
        job = api.request(f"/api/jobs/{self.fixture['job_id']}")
        require(
            job["status"] == "queued" and job["attempts"] == 0,
            "The preserved unauthenticated manual job was lost or spuriously attempted.",
        )
        require(job["payload"]["page_budget"] == 3, "Queued job lost its configuration snapshot.")
        require(
            api.request("/api/notifications") == [],
            "Recovery created an unexpected notification or replay flood.",
        )

    def restart(self) -> None:
        self.compose(self.original, "restart", label="Restart both application roles")
        self.start(self.original)
        self.verify_state()
        self.verify_marker(self.original)

    def crash(self) -> None:
        self.compose(
            self.original,
            "kill",
            "--signal",
            "SIGKILL",
            "web",
            "collector",
            label="Send actual SIGKILL to web and collector",
        )
        self.start(self.original)
        self.verify_state()
        self.verify_marker(self.original)

    def backup(self) -> None:
        self.compose(self.original, "stop", label="Stop both services before complete backup")
        self.compose(
            self.original,
            "run",
            "--rm",
            "--no-deps",
            "--pull",
            "never",
            "collector",
            "backup",
            "/data/recovery.tgz",
            label="Documented collector backup command",
        )
        self.compose(
            self.original,
            "cp",
            "collector:/data/recovery.tgz",
            str(self.archive),
            label="Copy private backup from the stopped collector volume",
        )
        require(self.archive.is_file(), "Backup command did not produce the private archive.")
        self.archive.chmod(0o600)
        require(
            stat.S_IMODE(self.archive.stat().st_mode) == 0o600,
            "Host backup archive permissions must be 0600.",
        )
        with tarfile.open(self.archive, "r:gz") as archive:
            require(
                {"manifest.json", "app/vine-search.sqlite3", "session/verify-install-marker"}
                <= set(archive.getnames()),
                "Backup omitted database, manifest or private session marker.",
            )
            member = archive.extractfile("manifest.json")
            require(member is not None, "Backup manifest cannot be read.")
            with member:
                manifest = json.loads(member.read(65536))
            require(
                manifest["format"] == 1, "Backup format is not supported by this release verifier."
            )
            require(
                manifest["application_version"] == self.report["application_version"],
                "Backup version differs from the running application version.",
            )
        self.report["backup"] = {
            "created": True,
            "private_mode": "0600",
            "bytes": self.archive.stat().st_size,
            "contains_database_and_session": True,
        }

    def restore(self) -> None:
        self.projects_started.add(self.restored)
        self.compose(
            self.restored,
            "run",
            "--rm",
            "--no-deps",
            "--pull",
            "never",
            "-v",
            f"{self.archive}:/backup.tgz:ro",
            "collector",
            "restore",
            "/backup.tgz",
            "--data-dir",
            "/data",
            "--session-dir",
            "/session",
            label="Documented restore to a new Compose project's empty volumes",
        )
        self.dashboard = Dashboard(self.port)
        self.start(self.restored)
        self.inspect_mounts(self.restored)
        self.verify_state()
        self.verify_marker(self.restored)

    def sample_resources(self, project: str, phase: str) -> None:
        sample: Json = {"phase": phase, "browser_state": "idle; no Amazon login"}
        for service in ("web", "collector"):
            identity = self.container(project, service)
            output = self.command(
                ["docker", "stats", "--no-stream", "--format", "{{json .}}", identity],
                label=f"Sample idle {service} resources",
                timeout=20,
            ).stdout.strip()
            value = json.loads(output)
            sample[service] = {
                key: value.get(key) for key in ("CPUPerc", "MemUsage", "MemPerc", "PIDs")
            }
        self.report["resource_samples"].append(sample)

    def login_fixture(self) -> None:
        result = self.compose(
            self.original,
            "exec",
            "-T",
            "collector",
            "python",
            "/app/docker/verify-login.py",
            label="Actual noVNC fixture inside the supplied image",
            timeout=max(self.timeout, 300),
        )
        try:
            payload = json.loads(result)
        except json.JSONDecodeError as error:
            raise VerificationError(
                "The served-login fixture did not return its JSON evidence."
            ) from error
        checks = payload.get("checks", {})
        expected = (
            "exclusive_browser_ownership",
            "viewer_keyboard_completion_detection",
            "viewer_shutdown_after_completion",
            "persistent_session_headless_reuse",
            "served_reconnect_cancel",
            "served_timeout_revokes_viewer",
            "viewer_requires_capability",
        )
        require(
            all(checks.get(key) is True for key in expected),
            "The actual noVNC fixture did not pass every required lifecycle check.",
        )
        require(
            checks.get("client_javascript_errors") == [], "The noVNC fixture had browser errors."
        )
        # Omit viewer paths/capabilities and screenshot contents from this public report.
        self.report["served_login_fixture"] = {
            "mode": payload.get("mode"),
            "passed_checks": list(expected),
            "client_javascript_errors": 0,
        }

    def cleanup(self) -> None:
        for project in sorted(self.projects_started):
            self.compose(
                project,
                "down",
                "--timeout",
                "15",
                label="Remove test containers, retain volumes",
                timeout=60,
            )
        for volumes in self.volumes.values():
            for name in volumes.values():
                self.command(
                    ["docker", "volume", "inspect", "--format", "{{.Name}}", name],
                    label="Verify named volume survives normal down",
                    timeout=20,
                )
        self.report["volumes_retained"] = self.volumes
        self.report["test_containers_removed"] = True

    def run(self) -> int:
        started = time.monotonic()
        try:
            self.step("fresh_release_assets_and_local_image", self.preflight)
            self.step("image_setup_and_idempotent_private_configuration", self.setup)
            self.step("fresh_startup", lambda: self.start(self.original))
            self.step(
                "web_session_volume_isolation_and_no_source_mount",
                lambda: self.inspect_mounts(self.original),
            )
            self.step("csrf_settings_tracker_review_import_and_progress", self.exercise_api)
            self.step("private_session_marker_boundary", self.write_marker)
            self.step(
                "idle_resource_sample",
                lambda: self.sample_resources(self.original, "fresh-install"),
            )
            if self.with_login:
                self.step("actual_served_login_fixture", self.login_fixture)
            self.step("restart_preserves_settings_records_jobs_and_session", self.restart)
            self.step("sigkill_recovery_preserves_settings_records_jobs_and_session", self.crash)
            self.step("documented_complete_private_backup", self.backup)
            self.step("documented_restore_to_separate_fresh_volumes", self.restore)
            self.step(
                "restored_idle_resource_sample",
                lambda: self.sample_resources(self.restored, "restored"),
            )
            self.step("normal_uninstall_preserves_both_installations_volumes", self.cleanup)
            self.report["status"] = "pass"
            return 0
        except (
            VerificationError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            tarfile.TarError,
        ) as error:
            self.report["status"] = "failed"
            self.report["failure"] = (
                str(error)
                if isinstance(error, VerificationError)
                else (
                    f"Unexpected {type(error).__name__}; "
                    "inspect the named disposable test projects locally."
                )
            )
            print(self.report["failure"], file=sys.stderr, flush=True)
            if self.projects_started:
                try:
                    self.cleanup()
                except VerificationError:
                    self.report["cleanup"] = (
                        "incomplete; named test projects require local inspection"
                    )
            return 1
        finally:
            self.report["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            self.report["elapsed_seconds"] = round(time.monotonic() - started, 2)
            timings = self.dashboard.timings
            if timings:
                self.report["http_sample"] = {
                    "requests": len(timings),
                    "max_ms": max(timings),
                    "median_ms": sorted(timings)[len(timings) // 2],
                }
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.report_path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as target:
                json.dump(self.report, target, indent=2)
                target.write("\n")
            self.report_path.chmod(0o600)
            print(f"Verification {self.report['status']}; report: {self.report_path}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--directory",
        type=Path,
        required=True,
        help="Fresh unpacked release assets; no .env, runtime data or source checkout",
    )
    parser.add_argument("--image", required=True, help="Exact already-pulled release tag or digest")
    parser.add_argument("--port", type=int, default=18765, help="Free loopback-only dashboard port")
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional safe JSON report path; defaults inside private run directory",
    )
    parser.add_argument(
        "--timeout", type=int, default=180, help="Bounded Compose operation timeout, 60-600 seconds"
    )
    parser.add_argument(
        "--with-login",
        action="store_true",
        help="Also run the real served noVNC synthetic fixture inside the image",
    )
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("--port must be between 1024 and 65535")
    if not 60 <= args.timeout <= 600:
        parser.error("--timeout must be between 60 and 600 seconds")
    if args.report and args.report.expanduser().exists():
        parser.error("--report must name a new file; existing evidence will not be overwritten")
    if not args.image or args.image.startswith("-") or any(char.isspace() for char in args.image):
        parser.error("--image must be one explicit image reference")
    return InstallVerifier(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
