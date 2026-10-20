"Validated instance settings and JSON domain types; no browser dependencies."

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

Json = dict[str, Any]
DEFAULT_SETTINGS: Json = {
    "collection_enabled": True,
    "rfy_enabled": True,
    "afa_enabled": True,
    "collection_interval_minutes": 15,
    "page_budget": 5,
    "runtime_budget_seconds": 120,
    "review_sync_enabled": True,
    "review_sync_interval_minutes": 60,
    "review_page_budget": 10,
    "notifications_enabled": False,
    "notification_adapter": "webhook",
    "notification_url": "",
    "notification_secret": "",
    "notification_cadence": "immediate",
    "digest_minutes": 60,
    "quiet_start": "",
    "quiet_end": "",
    "timezone": "UTC",
    "notify_relists": False,
    "review_reminders_enabled": False,
    "review_reminder_age_days": 21,
    "review_personal_target_days": 0,
    "review_reminder_repeat_days": 7,
    "image_mode": "proxy",
    "retention_days": 365,
}
SETTING_BOUNDS = {
    "collection_interval_minutes": (5, 1440),
    "page_budget": (1, 100),
    "runtime_budget_seconds": (15, 1800),
    "review_sync_interval_minutes": (15, 10080),
    "review_page_budget": (1, 100),
    "digest_minutes": (5, 1440),
    "review_reminder_age_days": (1, 365),
    "review_personal_target_days": (0, 365),
    "review_reminder_repeat_days": (1, 90),
    "retention_days": (7, 3650),
}
SETTING_CHOICES = {
    "notification_adapter": {"webhook", "ntfy"},
    "notification_cadence": {"immediate", "digest"},
    "image_mode": {"proxy", "direct", "hidden"},
}
TRACKER_DEFAULTS: Json = {
    "name": "New tracker",
    "enabled": True,
    "query": "",
    "phrases": [],
    "phrase_mode": "any",
    "exclusions": [],
    "categories": [],
    "phrase_weight": 30,
    "category_weight": 20,
    "freshness_weight": 10,
    "min_score": 1,
    "freshness_hours": 168,
    "notify": False,
    "schedule_enabled": False,
    "interval_minutes": 15,
    "page_budget": 5,
}
JOB_KINDS = {"rfy", "afa", "search", "reviews", "login", "disconnect"}
TERMINAL_STATUSES = {"complete", "partial", "truncated", "failed", "needs_login", "cancelled"}
LOCAL_PROGRESS = {"not_started", "in_progress", "submitted"}
REVIEW_FIELDS = {
    "external_id",
    "asin",
    "marketplace",
    "title",
    "variant",
    "order_date",
    "observed_status",
    "observed_deadline",
    "product_url",
    "review_url",
    "rating",
    "source",
    "local_progress",
}


def utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def parse_time(value: str | datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    result = (
        value
        if isinstance(value, datetime)
        else datetime.fromisoformat(value.replace("Z", "+00:00"))
    )
    return result.replace(tzinfo=UTC) if result.tzinfo is None else result.astimezone(UTC)


def stamp(value: str | datetime | None = None) -> str:
    return parse_time(value).isoformat(timespec="seconds")


def text_value(value: Any, name: str, maximum: int = 1000, *, empty: bool = True) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be text")
    cleaned: str = value.strip()
    if len(cleaned) > maximum or (not empty and not cleaned):
        raise ValueError(f"{name} must contain {'0' if empty else '1'}-{maximum} characters")
    if any(ord(char) < 32 and char not in "\n\t" for char in cleaned):
        raise ValueError(f"{name} contains control characters")
    return cleaned


def integer(value: Any, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f"{name} must be an integer between {low} and {high}")
    return value


def safe_amazon_url(value: Any, *, image: bool = False) -> str:
    cleaned = text_value(value or "", "URL", 2048)
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    hosts = (
        {
            "m.media-amazon.com",
            "images-na.ssl-images-amazon.com",
            "images-eu.ssl-images-amazon.com",
            "images.amazon.com",
        }
        if image
        else {"amazon.com", "www.amazon.com"}
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("URL must use an approved HTTPS Amazon host")
    return cleaned


def validate_settings(current: Json, patch: Json) -> Json:
    if not isinstance(patch, dict):
        raise ValueError("Settings must be an object")
    unknown = set(patch) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    result = dict(current)
    for key, value in patch.items():
        if isinstance(DEFAULT_SETTINGS[key], bool):
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be true or false")
        elif key in SETTING_BOUNDS:
            integer(value, key, *SETTING_BOUNDS[key])
        elif key in SETTING_CHOICES:
            if not isinstance(value, str) or value not in SETTING_CHOICES[key]:
                raise ValueError(f"Invalid {key}")
        else:
            value = text_value(value, key, 2048)
        if key in {"notification_secret", "notification_url"} and value == "***":
            continue
        if key in {"notification_secret", "notification_url"} and any(
            ord(char) < 32 for char in value
        ):
            raise ValueError(f"{key} cannot contain control characters")
        result[key] = value
    try:
        ZoneInfo(result["timezone"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    for key in ("quiet_start", "quiet_end"):
        if result[key] and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", result[key]):
            raise ValueError(f"{key} must be HH:MM")
    if bool(result["quiet_start"]) != bool(result["quiet_end"]):
        raise ValueError("Set both quiet_start and quiet_end, or clear both")
    if result["notification_url"]:
        url = urlparse(result["notification_url"])
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.fragment
        ):
            raise ValueError(
                "notification_url must be HTTP(S), without embedded credentials or fragment"
            )
        if result["notification_adapter"] == "ntfy" and not url.path.strip("/"):
            raise ValueError("ntfy destination must include a topic path")
    if result["notifications_enabled"] and not result["notification_url"]:
        raise ValueError("Configure a destination before enabling notifications")
    return result


def validate_tracker(data: Json, previous: Json | None = None) -> Json:
    allowed = set(TRACKER_DEFAULTS)
    if set(data) - allowed - {"id", "created_at", "updated_at"}:
        raise ValueError("Unknown tracker field")
    result = dict(TRACKER_DEFAULTS)
    if previous:
        result.update({k: v for k, v in previous.items() if k in allowed})
    result.update({k: v for k, v in data.items() if k in allowed})
    result["name"] = text_value(result["name"], "name", 120, empty=False)
    result["query"] = text_value(result["query"], "query", 200)
    for key in ("enabled", "notify", "schedule_enabled"):
        if not isinstance(result[key], bool):
            raise ValueError(f"{key} must be true or false")
    for key in ("phrases", "exclusions", "categories"):
        if not isinstance(result[key], list) or len(result[key]) > 50:
            raise ValueError(f"{key} must be a list with at most 50 entries")
        result[key] = list(dict.fromkeys(text_value(v, key, 120, empty=False) for v in result[key]))
    if not isinstance(result["phrase_mode"], str) or result["phrase_mode"] not in {"any", "all"}:
        raise ValueError("phrase_mode must be any or all")
    for key in ("phrase_weight", "category_weight", "freshness_weight", "min_score"):
        integer(result[key], key, 0, 1000)
    integer(result["freshness_hours"], "freshness_hours", 1, 8760)
    integer(result["interval_minutes"], "interval_minutes", 5, 10080)
    integer(result["page_budget"], "page_budget", 1, 100)
    if result["schedule_enabled"] and not result["query"]:
        raise ValueError("A scheduled tracker requires a live query")
    return result


def clean_product(data: Json) -> Json:
    asin = text_value(data.get("asin", ""), "ASIN", 10).upper()
    if not re.fullmatch(r"[A-Z0-9]{10}", asin):
        raise ValueError("ASIN must contain 10 letters or digits")
    if data.get("marketplace", "amazon.com") != "amazon.com":
        raise ValueError("Only amazon.com is supported")
    return {
        "asin": asin,
        "marketplace": "amazon.com",
        "title": text_value(data.get("title", ""), "title", 1000, empty=False),
        "category": text_value(data.get("category") or "", "category", 200),
        "variant": text_value(data.get("variant") or "", "variant", 500),
        "image_url": safe_amazon_url(data.get("image_url", ""), image=True),
        "product_url": safe_amazon_url(
            data.get("product_url") or f"https://www.amazon.com/dp/{asin}"
        ),
        "vine_url": safe_amazon_url(data.get("vine_url", "")),
    }
