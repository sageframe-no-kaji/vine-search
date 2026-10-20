"""Exercise the shipped shell installer without a Docker daemon or real state."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DEFAULT_IMAGE = "ghcr.io/sageframe-no-kaji/vine-search:0.1.1"
PINNED_IMAGE = "ghcr.io/sageframe-no-kaji/vine-search@sha256:" + "a" * 64
FAKE_DOCKER = r"""
import json, os, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values

arguments = sys.argv[1:]
directory = Path.cwd()
with (directory / "docker-calls.jsonl").open("a") as log:
    log.write(json.dumps(arguments) + "\n")
if arguments[:2] == ["compose", "version"]:
    print("Docker Compose fixture")
elif arguments[:3] == ["compose", "config", "--images"]:
    values = dotenv_values(directory / ".env")
    image = (os.environ.get("VINE_SEARCH_IMAGE") or values.get("VINE_SEARCH_IMAGE")
             or os.environ["FIXTURE_DEFAULT_IMAGE"])
    print(image)
    print("fixture/other:1" if os.environ.get("FIXTURE_MIXED_IMAGES") else image)
elif arguments[:1] == ["pull"]:
    if os.environ.get("FIXTURE_PULL_FAILURE"):
        raise SystemExit(17)
elif arguments[:1] == ["run"]:
    if "--entrypoint" in arguments:
        environment = dict(os.environ)
        for index, argument in enumerate(arguments):
            if argument == "--env":
                key, value = arguments[index + 1].split("=", 1)
                environment[key] = value
        result = subprocess.run([sys.executable, "-", str(directory)],
                                input=sys.stdin.read(), text=True, env=environment)
        raise SystemExit(result.returncode)
    assert arguments[-3:] == ["setup", "--directory", "/install"]
    config = directory / ".env"
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write("VINE_SEARCH_IMAGE=" + os.environ["FIXTURE_DEFAULT_IMAGE"]
                     + "\nVINE_SEARCH_COLLECTOR_SECRET=fixture-private-secret"
                     + "\nVINE_SEARCH_PORT=8765\n")
elif arguments[:1] == ["compose"]:
    assert arguments[1:] in (["config", "--quiet"], ["pull"], ["up", "-d", "--no-build", "--wait"])
    with (directory / "started-images.jsonl").open("a") as log:
        log.write(json.dumps(os.environ.get("VINE_SEARCH_IMAGE")) + "\n")
else:
    raise AssertionError(arguments)
"""


@pytest.fixture
def installation(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    directory = tmp_path / "installation"
    (directory / "docker").mkdir(parents=True)
    shutil.copyfile("docker/install.sh", directory / "docker/install.sh")
    executable = tmp_path / "bin/docker"
    executable.parent.mkdir()
    executable.write_text(f"#!{sys.executable}\n" + FAKE_DOCKER)
    executable.chmod(0o755)
    environment = {
        key: value for key, value in os.environ.items() if not key.startswith("VINE_SEARCH_")
    }
    environment["PATH"] = f"{executable.parent}:{environment['PATH']}"
    environment["FIXTURE_DEFAULT_IMAGE"] = DEFAULT_IMAGE
    return directory, environment


def run_installer(installation: tuple[Path, dict[str, str]]) -> subprocess.CompletedProcess[str]:
    directory, environment = installation
    result = subprocess.run(
        ["sh", "docker/install.sh"],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "fixture-private-secret" not in result.stdout + result.stderr
    assert not list(directory.glob(".env.install-*"))
    return result


def image_in_config(directory: Path) -> str:
    from dotenv import dotenv_values

    value = dotenv_values(directory / ".env")["VINE_SEARCH_IMAGE"]
    assert isinstance(value, str)
    return value


def calls(directory: Path) -> list[list[str]]:
    return [
        json.loads(line) for line in (directory / "docker-calls.jsonl").read_text().splitlines()
    ]


@pytest.mark.parametrize("image", [DEFAULT_IMAGE, PINNED_IMAGE])
def test_fresh_install_persists_selected_image_for_later_compose(
    installation: tuple[Path, dict[str, str]],
    image: str,
) -> None:
    directory, environment = installation
    if image != DEFAULT_IMAGE:
        environment["VINE_SEARCH_IMAGE"] = image
    result = run_installer(installation)
    assert result.returncode == 0, result.stderr
    assert image_in_config(directory) == image
    assert (directory / ".env").stat().st_mode & 0o777 == 0o600
    environment.pop("VINE_SEARCH_IMAGE", None)
    subsequent = subprocess.run(
        ["docker", "compose", "config", "--images"],
        cwd=directory,
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert set(subsequent.stdout.splitlines()) == {image}


def test_existing_image_and_all_settings_survive_repeated_install(
    installation: tuple[Path, dict[str, str]],
) -> None:
    directory, _ = installation
    contents = (
        "# Existing operator configuration\n"
        f"export VINE_SEARCH_IMAGE = '{PINNED_IMAGE}' # retained\n"
        "VINE_SEARCH_COLLECTOR_SECRET=fixture-private-secret\n"
        "VINE_SEARCH_PORT=18766\n"
        "UNRELATED='$(touch should-not-exist)'\n"
    ).encode()
    config = directory / ".env"
    config.write_bytes(contents)
    config.chmod(0o600)
    for _ in range(2):
        result = run_installer(installation)
        assert result.returncode == 0, result.stderr
        assert config.read_bytes() == contents
    assert not (directory / "should-not-exist").exists()
    pulls = [row for row in calls(directory) if row[0] == "pull"]
    assert pulls == [["pull", PINNED_IMAGE], ["pull", PINNED_IMAGE]]
    assert all("setup" not in row for row in calls(directory))


def test_explicit_upgrade_persists_atomically_preserving_other_fields(
    installation: tuple[Path, dict[str, str]],
) -> None:
    directory, environment = installation
    environment["VINE_SEARCH_IMAGE"] = PINNED_IMAGE
    config = directory / ".env"
    config.write_bytes(
        b"# retained\r\nVINE_SEARCH_IMAGE='example/old:1'\r\n"
        b"VINE_SEARCH_COLLECTOR_SECRET=fixture-private-secret\r\n"
        b"export VINE_SEARCH_IMAGE=example/old:2\r\nVINE_SEARCH_PORT=18766\r\n"
    )
    result = run_installer(installation)
    assert result.returncode == 0, result.stderr
    assert (
        config.read_bytes()
        == (
            f"# retained\r\nVINE_SEARCH_IMAGE={PINNED_IMAGE}\r\n"
            "VINE_SEARCH_COLLECTOR_SECRET=fixture-private-secret\r\n"
            "VINE_SEARCH_PORT=18766\r\n"
        ).encode()
    )
    assert config.stat().st_mode & 0o777 == 0o600
    environment.pop("VINE_SEARCH_IMAGE")
    assert run_installer(installation).returncode == 0
    assert image_in_config(directory) == PINNED_IMAGE


def test_update_preserves_multiline_values_and_separating_whitespace(
    installation: tuple[Path, dict[str, str]],
) -> None:
    directory, environment = installation
    environment["VINE_SEARCH_IMAGE"] = PINNED_IMAGE
    original = (
        "# retained\n\nVINE_SEARCH_IMAGE=example/old:1\n"
        "UNRELATED='first line\nVINE_SEARCH_IMAGE=inside-quoted-value\nlast line'\n"
        "VINE_SEARCH_COLLECTOR_SECRET=fixture-private-secret\n"
    )
    config = directory / ".env"
    config.write_text(original)
    result = run_installer(installation)
    assert result.returncode == 0, result.stderr
    assert config.read_text() == original.replace("example/old:1", PINNED_IMAGE)


def test_missing_image_entry_is_pinned_without_changing_settings(
    installation: tuple[Path, dict[str, str]],
) -> None:
    directory, _ = installation
    config = directory / ".env"
    original = "VINE_SEARCH_COLLECTOR_SECRET=fixture-private-secret\nVINE_SEARCH_PORT=18766"
    config.write_text(original)
    result = run_installer(installation)
    assert result.returncode == 0, result.stderr
    assert config.read_text() == original + f"\nVINE_SEARCH_IMAGE={DEFAULT_IMAGE}\n"


def test_pull_failure_preserves_prior_configuration(
    installation: tuple[Path, dict[str, str]],
) -> None:
    directory, environment = installation
    config = directory / ".env"
    config.write_text("VINE_SEARCH_IMAGE=example/old:1\n")
    original = config.read_bytes()
    environment.update(VINE_SEARCH_IMAGE=PINNED_IMAGE, FIXTURE_PULL_FAILURE="1")
    result = run_installer(installation)
    assert result.returncode == 17
    assert config.read_bytes() == original
    assert all(row[0] != "run" for row in calls(directory))


@pytest.mark.parametrize("override", ["", "bad image", "example:1\nexample:2", "-bad"])
def test_invalid_explicit_image_never_starts_or_mutates(
    installation: tuple[Path, dict[str, str]],
    override: str,
) -> None:
    directory, environment = installation
    environment["VINE_SEARCH_IMAGE"] = override
    assert run_installer(installation).returncode != 0
    assert not (directory / ".env").exists()
    assert all(row[0] not in {"pull", "run"} for row in calls(directory))


def test_mixed_role_images_stop_before_update(
    installation: tuple[Path, dict[str, str]],
) -> None:
    directory, environment = installation
    environment["FIXTURE_MIXED_IMAGES"] = "1"
    config = directory / ".env"
    config.write_text(f"VINE_SEARCH_IMAGE={PINNED_IMAGE}\n")
    before = config.read_bytes()
    result = run_installer(installation)
    assert result.returncode != 0
    assert config.read_bytes() == before
    assert all(row[0] not in {"pull", "run"} for row in calls(directory))
