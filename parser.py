"""Read refuge names and nightly availability from the official TMB pages."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date

BASE_URL = "https://montourdumontblanc.com"

_CELL_RE = re.compile(
    r"<(?:a|span)\b([^>]*\bcal-cell--(dispo|full|closed|past)\b[^>]*)>",
    re.IGNORECASE,
)
_ATTR_RE = re.compile(r"""([\w:-]+)="([^"]*)\"""")
_CARD_RE = re.compile(
    r"<a\b([^>]*\bclass=\"[^\"]*\brefuge-card\b[^\"]*\"[^>]*)>",
    re.IGNORECASE,
)
_LEADING_DATE_RE = re.compile(
    r"(\d{2})/(\d{2})/(\d{4})\s*[—–\-]\s*(.*)$",
    re.DOTALL,
)
_ANY_DATE_RE = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
_BEDS_RE = re.compile(r"(\d+)\b")
_PLACES_RE = re.compile(
    r"cal-cell__places\b[^>]*>\s*([^<]+)",
    re.IGNORECASE,
)

_STATUS_BY_CLASS = {
    "dispo": "available",
    "full": "full",
    "closed": "closed",
    "past": "past",
}


@dataclass(frozen=True)
class Refuge:
    name: str
    slug: str


@dataclass(frozen=True)
class Night:
    date: date
    status: str
    beds: int | None


def reservation_url(slug: str, day: date) -> str:
    return f"{BASE_URL}/fr/reservation/{slug}/{day:%Y%m%d}"


def parse_refuges(page_html: str) -> list[Refuge]:
    """Return the refuges linked from the official index, in name order."""
    found: dict[str, Refuge] = {}
    for match in _CARD_RE.finditer(page_html):
        attrs = _attributes(match.group(1))
        href = html.unescape(attrs.get("href", ""))
        slug = _slug_from_href(href)
        name = html.unescape(attrs.get("title", "")).strip()
        if not slug or not name or slug in found:
            continue
        found[slug] = Refuge(name=name, slug=slug)
    return sorted(found.values(), key=lambda refuge: refuge.name.casefold())


def parse_calendar(page_html: str) -> dict[date, Night]:
    """Map each dated calendar cell to its status and bed count."""
    nights: dict[date, Night] = {}
    for match in _CELL_RE.finditer(page_html):
        attrs = _attributes(match.group(1))
        title = html.unescape(attrs.get("title", ""))
        day, beds = _parse_title(title)
        if day is None:
            continue
        status = _STATUS_BY_CLASS[match.group(2).lower()]
        if status == "available" and beds is None:
            beds = _beds_from_places(page_html, match.end())
        if status == "full":
            beds = 0
        nights[day] = Night(date=day, status=status, beds=beds)
    return nights


def _attributes(source: str) -> dict[str, str]:
    return {name.lower(): value for name, value in _ATTR_RE.findall(source)}


def _slug_from_href(href: str) -> str:
    marker = "/fr/refuges/"
    if marker not in href:
        return ""
    slug = href.split(marker, 1)[1].split("/", 1)[0].split("?", 1)[0].strip()
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        return ""
    return slug


def _parse_title(title: str) -> tuple[date | None, int | None]:
    text = " ".join(title.split())
    leading = _LEADING_DATE_RE.match(text)
    if leading:
        day = _safe_date(leading.group(1), leading.group(2), leading.group(3))
        beds_match = _BEDS_RE.match(leading.group(4).strip())
        beds = int(beds_match.group(1)) if beds_match else None
        return day, beds
    found = _ANY_DATE_RE.search(text)
    if not found:
        return None, None
    return _safe_date(found.group(1), found.group(2), found.group(3)), None


def _safe_date(day: str, month: str, year: str) -> date | None:
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _beds_from_places(page_html: str, start: int) -> int | None:
    window = page_html[start : start + 400]
    match = _PLACES_RE.search(window)
    if not match:
        return None
    beds_match = _BEDS_RE.search(match.group(1))
    if not beds_match:
        return None
    return int(beds_match.group(1))
