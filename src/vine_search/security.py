"""Origin, request-forgery and untrusted remote-content boundaries."""

import hashlib
import hmac
import secrets
import time
from ipaddress import IPv4Network, IPv6Address, IPv6Network, ip_address, ip_network
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

CSRF_COOKIE = "vine_csrf"
LOGIN_COOKIE = "vine_login_capability"
IMAGE_HOSTS = frozenset(
    {
        "m.media-amazon.com",
        "images-na.ssl-images-amazon.com",
        "images-eu.ssl-images-amazon.com",
        "images.amazon.com",
    }
)
ClientNetwork = IPv4Network | IPv6Network


def client_networks(entries: tuple[str, ...]) -> tuple[ClientNetwork, ...]:
    """Validate deployment IPs/CIDRs before serving any requests."""
    try:
        return tuple(ip_network(entry.strip()) for entry in entries)
    except ValueError as exc:
        raise ValueError(
            "VINE_SEARCH_ALLOWED_CLIENTS must contain comma-separated IP addresses "
            "or CIDRs with their host bits cleared."
        ) from exc


def client_allowed(host: str | None, networks: tuple[ClientNetwork, ...]) -> bool:
    """Check the connection peer, never an HTTP forwarding header."""
    if not networks:
        return True
    if host is None:
        return False
    try:
        address = ip_address(host)
    except ValueError:
        return False
    if isinstance(address, IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(address in network for network in networks)


def csrf_token(secret: str) -> str:
    """Issue an expiring signed double-submit token."""
    value = f"{int(time.time())}.{secrets.token_hex(24)}"
    return value + "." + hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def valid_csrf(token: str, secret: str) -> bool:
    """Accept only signed tokens issued within the previous day."""
    try:
        stamp, nonce, signature = token.split(".")
        age = time.time() - int(stamp)
    except (ValueError, TypeError):
        return False
    if not 0 <= age <= 86400 or len(nonce) != 48:
        return False
    expected = hmac.new(secret.encode(), f"{stamp}.{nonce}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def check_write(request: Request, secret: str) -> None:
    """Require same-origin requests with an unforgeable browser token."""
    supplied = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if not supplied or not hmac.compare_digest(supplied, cookie) or not valid_csrf(cookie, secret):
        raise HTTPException(403, "Reload the page before making changes.")
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Changes must come from this application's origin.")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Cross-site requests are not accepted.")


def image_url_allowed(url: str) -> bool:
    """Constrain image requests to known Amazon CDN HTTPS endpoints."""
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in IMAGE_HOSTS
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False
