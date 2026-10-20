"""Alert rules: toast only when a date newly has enough beds."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checker import Watch, check_watches, classify_watch  # noqa: E402
from parser import Night  # noqa: E402

WATCH = Watch(
    id="mottets-2027-06-10",
    slug="refuge-des-mottets",
    name="Refuge des Mottets",
    date=date(2027, 6, 10),
    min_beds=2,
)


def _night(status: str, beds: int | None) -> Night:
    return Night(date=WATCH.date, status=status, beds=beds)


class ClassifyWatchTests(unittest.TestCase):
    def test_first_open_night_notifies(self) -> None:
        status = classify_watch(WATCH, _night("available", 16), previous_open=False)
        self.assertTrue(status.is_open)
        self.assertTrue(status.should_notify)
        self.assertEqual(status.detail, "Open, 16 beds")
        self.assertIn("/fr/reservation/refuge-des-mottets/20270610", status.url)

    def test_still_open_stays_quiet(self) -> None:
        status = classify_watch(WATCH, _night("available", 16), previous_open=True)
        self.assertTrue(status.is_open)
        self.assertFalse(status.should_notify)

    def test_below_minimum_is_not_open(self) -> None:
        status = classify_watch(WATCH, _night("available", 1), previous_open=False)
        self.assertFalse(status.is_open)
        self.assertFalse(status.should_notify)
        self.assertEqual(status.detail, "1 bed, need 2")

    def test_reopening_notifies_again(self) -> None:
        closed = classify_watch(WATCH, _night("full", 0), previous_open=True)
        self.assertFalse(closed.is_open)
        self.assertFalse(closed.should_notify)
        reopened = classify_watch(WATCH, _night("available", 4), previous_open=False)
        self.assertTrue(reopened.should_notify)

    def test_missing_date(self) -> None:
        status = classify_watch(WATCH, None, previous_open=False)
        self.assertEqual(status.status, "missing")
        self.assertEqual(status.detail, "Date not on calendar")
        self.assertFalse(status.should_notify)

    def test_error_keeps_the_previous_open_flag(self) -> None:
        status = classify_watch(
            WATCH,
            None,
            previous_open=True,
            error="timed out",
        )
        self.assertEqual(status.status, "error")
        self.assertTrue(status.is_open)
        self.assertFalse(status.should_notify)


class CheckWatchesTests(unittest.TestCase):
    def test_one_download_per_refuge(self) -> None:
        calls: list[str] = []

        def fetch(url: str) -> str:
            calls.append(url)
            if url.endswith("/refuge-des-mottets"):
                return (ROOT / "tests" / "fixtures" / "calendar_snippet.html").read_text(
                    encoding="utf-8"
                )
            return "<div></div>"

        other = Watch("other", "gite-michel-fagot", "Gîte Michel Fagot", date(2027, 6, 11), 1)
        same_refuge = Watch("same", WATCH.slug, WATCH.name, date(2027, 6, 24), 1)
        results, state = check_watches([WATCH, same_refuge, other], {}, fetch=fetch)
        self.assertEqual(len(calls), 2)
        by_id = {item.watch_id: item for item in results}
        self.assertTrue(by_id[WATCH.id].should_notify)
        self.assertEqual(by_id[same_refuge.id].detail, "Full")
        self.assertEqual(by_id[other.id].detail, "Date not on calendar")
        self.assertTrue(state[WATCH.id]["open"])
        self.assertFalse(state[same_refuge.id]["open"])


if __name__ == "__main__":
    unittest.main()
