"""Decide when a watched refuge date is open, and download the pages."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from parser import Night, parse_calendar, reservation_url

USER_AGENT = (
    "TMBRefugeWatch/1.0 (personal availability checker; "
    "+https://montourdumontblanc.com)"
)
BASE_URL = "https://montourdumontblanc.com"
MIN_INTERVAL_MINUTES = 10
DEFAULT_INTERVAL_MINUTES = 15


@dataclass(frozen=True)
class Watch:
    id: str
    slug: str
    name: str
    date: date
    min_beds: int

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "date": self.date.isoformat(),
            "min_beds": self.min_beds,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Watch":
        return cls(
            id=str(raw["id"]),
            slug=str(raw["slug"]),
            name=str(raw["name"]),
            date=date.fromisoformat(str(raw["date"])),
            min_beds=max(1, int(raw["min_beds"])),
        )


@dataclass(frozen=True)
class WatchStatus:
    watch_id: str
    status: str
    beds: int | None
    is_open: bool
    should_notify: bool
    detail: str
    url: str
    checked_at: str
    error: str | None = None


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "fr",
            "Accept": "text/html",
        },
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace")


def load_config(path: Path) -> tuple[int, list[Watch]]:
    if not path.exists():
        return DEFAULT_INTERVAL_MINUTES, []
    raw = json.loads(path.read_text(encoding="utf-8"))
    interval = max(MIN_INTERVAL_MINUTES, int(raw.get("interval_minutes", DEFAULT_INTERVAL_MINUTES)))
    watches = [Watch.from_dict(item) for item in raw.get("watches", [])]
    return interval, watches


def save_config(path: Path, interval_minutes: int, watches: list[Watch]) -> None:
    payload = {
        "interval_minutes": max(MIN_INTERVAL_MINUTES, int(interval_minutes)),
        "watches": [watch.to_dict() for watch in watches],
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def classify_watch(
    watch: Watch,
    night: Night | None,
    previous_open: bool,
    *,
    error: str | None = None,
    checked_at: str | None = None,
) -> WatchStatus:
    """Return the status to show, and whether this check should raise a toast.

    A toast fires only when the date newly has at least the requested beds.
    A failed download keeps the previous open flag so a later success does
    not alert again for a night that never closed.
    """
    when = checked_at or datetime.now().astimezone().isoformat(timespec="minutes")
    url = reservation_url(watch.slug, watch.date)
    if error:
        return WatchStatus(
            watch_id=watch.id,
            status="error",
            beds=None,
            is_open=previous_open,
            should_notify=False,
            detail=f"Error: {error}",
            url=url,
            checked_at=when,
            error=error,
        )
    if night is None:
        return WatchStatus(
            watch_id=watch.id,
            status="missing",
            beds=None,
            is_open=False,
            should_notify=False,
            detail="Date not on calendar",
            url=url,
            checked_at=when,
        )

    beds = night.beds
    if night.status == "available":
        bed_count = beds or 0
        is_open = bed_count >= watch.min_beds
        noun = "bed" if bed_count == 1 else "beds"
        if is_open:
            detail = f"Open, {bed_count} {noun}"
        else:
            detail = f"{bed_count} {noun}, need {watch.min_beds}"
        status = "available"
    elif night.status == "full":
        is_open = False
        detail = "Full"
        status = "full"
        beds = 0
    elif night.status == "closed":
        is_open = False
        detail = "Closed"
        status = "closed"
    elif night.status == "past":
        is_open = False
        detail = "Past"
        status = "past"
    else:
        is_open = False
        detail = night.status
        status = night.status

    return WatchStatus(
        watch_id=watch.id,
        status=status,
        beds=beds,
        is_open=is_open,
        should_notify=is_open and not previous_open,
        detail=detail,
        url=url,
        checked_at=when,
    )


def check_watches(
    watches: list[Watch],
    state: dict,
    *,
    fetch=fetch_text,
) -> tuple[list[WatchStatus], dict]:
    """Download each watched refuge once and classify every date on it."""
    grouped: dict[str, list[Watch]] = {}
    for watch in watches:
        grouped.setdefault(watch.slug, []).append(watch)

    results: list[WatchStatus] = []
    new_state: dict = {}
    for slug, group in grouped.items():
        nights: dict[date, Night] | None = None
        error: str | None = None
        try:
            page = fetch(f"{BASE_URL}/fr/refuges/{slug}")
            nights = parse_calendar(page)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            error = _short_error(exc)
        except Exception as exc:  # keep one bad page from stopping the other refuges
            error = _short_error(exc)

        for watch in group:
            previous_open = bool(state.get(watch.id, {}).get("open", False))
            night = None if nights is None else nights.get(watch.date)
            status = classify_watch(watch, night, previous_open, error=error)
            results.append(status)
            new_state[watch.id] = {
                "open": status.is_open,
                "status": status.status,
                "beds": status.beds,
                "checked_at": status.checked_at,
                "error": status.error,
            }
    return results, new_state


def _short_error(exc: BaseException) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message[:180]
