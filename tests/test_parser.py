"""Parser coverage for the official refuge index and calendar markup."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parser import parse_calendar, parse_refuges  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class CalendarParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.nights = parse_calendar(
            (FIXTURES / "calendar_snippet.html").read_text(encoding="utf-8")
        )

    def test_available_night_has_bed_count(self) -> None:
        night = self.nights[date(2027, 6, 10)]
        self.assertEqual(night.status, "available")
        self.assertEqual(night.beds, 16)

    def test_singular_disponible(self) -> None:
        night = self.nights[date(2027, 6, 11)]
        self.assertEqual(night.status, "available")
        self.assertEqual(night.beds, 1)

    def test_full_night(self) -> None:
        night = self.nights[date(2027, 6, 24)]
        self.assertEqual(night.status, "full")
        self.assertEqual(night.beds, 0)

    def test_closed_night(self) -> None:
        night = self.nights[date(2026, 10, 20)]
        self.assertEqual(night.status, "closed")
        self.assertIsNone(night.beds)

    def test_past_night_uses_date_later_in_the_title(self) -> None:
        night = self.nights[date(2026, 10, 1)]
        self.assertEqual(night.status, "past")

    def test_bed_count_falls_back_to_the_places_span(self) -> None:
        night = self.nights[date(2027, 6, 12)]
        self.assertEqual(night.status, "available")
        self.assertEqual(night.beds, 7)

    def test_missing_date_is_absent(self) -> None:
        self.assertNotIn(date(2027, 7, 1), self.nights)


class RefugeListParserTests(unittest.TestCase):
    def test_names_slugs_and_duplicates(self) -> None:
        page = (FIXTURES / "refuges_snippet.html").read_text(encoding="utf-8")
        refuges = parse_refuges(page)
        self.assertEqual(
            [(refuge.name, refuge.slug) for refuge in refuges],
            [
                ("Chalet 'Le Dolent'", "chalet-le-dolent"),
                ("Refuge des Mottets", "refuge-des-mottets"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
