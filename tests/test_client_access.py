"""Operator network access, including real socket and forwarding-header attacks."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from vine_search.config import Config
from vine_search.security import client_allowed, client_networks
from vine_search.web import create_app


@pytest.mark.parametrize(
    ("peer", "allowed"),
    [
        ("100.100.100.10", True),
        ("100.100.100.11", False),
        ("192.0.2.254", True),
        ("192.0.3.1", False),
        ("fd7a:115c:a1e0::42", True),
        ("fd7a:115c:a1e1::42", False),
        ("::ffff:100.100.100.10", True),
        ("::ffff:100.100.100.11", False),
        ("not-an-address", False),
        (None, False),
    ],
)
def test_ip_and_cidr_membership(peer: str | None, allowed: bool) -> None:
    networks = client_networks(("100.100.100.10", "192.0.2.0/24", "fd7a:115c:a1e0::/48"))
    assert client_allowed(peer, networks) is allowed


@pytest.mark.parametrize("setting", ["host.example", "192.0.2.1/24", "fd7a::1/64", ",", "bad/33"])
def test_bad_allowlist_fails_before_startup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: str
) -> None:
    monkeypatch.setenv("VINE_SEARCH_ALLOWED_CLIENTS", setting)
    with pytest.raises(ValueError, match="VINE_SEARCH_ALLOWED_CLIENTS"):
        create_app(Config(data_dir=tmp_path / "unused", collector_secret="test-secret"))
    assert not (tmp_path / "unused").exists()


def test_empty_allowlist_preserves_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VINE_SEARCH_ALLOWED_CLIENTS", raising=False)
    assert Config().allowed_clients == ()
    monkeypatch.setenv("VINE_SEARCH_ALLOWED_CLIENTS", "")
    assert Config().allowed_clients == ()
    assert client_allowed("testclient", client_networks(Config().allowed_clients))
    assert client_networks((" 127.0.0.1 ", " ::1/128 ")) == client_networks(("127.0.0.1", "::1"))


@pytest.mark.parametrize("peer", ["100.100.100.11", "fd7a:115c:a1e0::11"])
def test_http_and_websocket_deny_unlisted_peers_even_with_spoofed_headers(
    tmp_path: Path, peer: str
) -> None:
    cfg = Config(
        data_dir=tmp_path,
        collector_secret="test-secret",
        allowed_hosts=("testserver",),
        allowed_clients=("127.0.0.1", "::1", "100.100.100.10"),
    )
    headers = {
        "x-forwarded-for": "100.100.100.10",
        "forwarded": 'for="100.100.100.10"',
        "x-real-ip": "100.100.100.10",
        "origin": "http://testserver",
        "cookie": "vine_login_capability=stolen-capability",
    }
    with TestClient(create_app(cfg), client=(peer, 12345)) as client:
        for path in ("/", "/health", "/api/bootstrap", "/login-viewer/session/vnc.html"):
            assert client.get(path, headers=headers).status_code == 403
        assert client.post("/api/jobs", headers=headers, json={"kind": "rfy"}).status_code == 403
        with (
            pytest.raises(WebSocketDisconnect) as denied,
            client.websocket_connect("/login-viewer/session/websockify", headers=headers),
        ):
            pytest.fail("An unlisted peer must not reach the viewer")
        assert denied.value.code == 1008


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1", "fd7a:115c:a1e0::42"])
def test_allowed_peers_reach_health_despite_hostile_forwarding_headers(
    tmp_path: Path, peer: str
) -> None:
    cfg = Config(
        data_dir=tmp_path,
        collector_secret="test-secret",
        allowed_hosts=("testserver",),
        allowed_clients=("127.0.0.1", "::1", "fd7a:115c:a1e0::/48"),
    )
    with TestClient(create_app(cfg), client=(peer, 12345)) as client:
        assert client.get("/health", headers={"x-forwarded-for": "203.0.113.1"}).status_code == 200


@pytest.mark.parametrize("allowed_clients, expected", [("192.0.2.10", 403), ("127.0.0.1", 200)])
def test_shipped_server_uses_socket_peer_not_forwarded_headers(
    tmp_path: Path, allowed_clients: str, expected: int
) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "VINE_SEARCH_DATA_DIR": str(tmp_path / "data"),
        "VINE_SEARCH_COLLECTOR_SECRET": "socket-test-secret",
        "VINE_SEARCH_ALLOWED_HOSTS": "127.0.0.1",
        "VINE_SEARCH_ALLOWED_CLIENTS": allowed_clients,
        # Even this Uvicorn setting cannot enable headers when the CLI disables them.
        "FORWARDED_ALLOW_IPS": "*",
    }
    with subprocess.Popen(
        [sys.executable, "-m", "vine_search", "web", "--host", "127.0.0.1", "--port", str(port)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as process:
        try:
            url = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + 10
            with httpx.Client(trust_env=False) as client:
                while True:
                    try:
                        response = client.get(
                            url + "/health",
                            headers={"x-forwarded-for": "192.0.2.10"},
                            timeout=0.5,
                        )
                        break
                    except httpx.ConnectError:
                        if process.poll() is not None or time.monotonic() >= deadline:
                            pytest.fail("The shipped web command failed to start")
                        time.sleep(0.05)
            assert response.status_code == expected
            if expected == 403:
                with (
                    pytest.raises(InvalidStatus) as denied,
                    connect(
                        f"ws://127.0.0.1:{port}/login-viewer/session/websockify",
                        origin=url,
                        additional_headers={
                            "X-Forwarded-For": "192.0.2.10",
                            "Cookie": "vine_login_capability=stolen-capability",
                        },
                        proxy=None,
                    ),
                ):
                    pytest.fail("Forwarded headers must not bypass the WebSocket peer check")
                assert denied.value.response.status_code == 403
        finally:
            process.terminate()
            process.wait(timeout=5)
