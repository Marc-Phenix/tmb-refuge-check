"""Toast XML includes the official reservation link."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from notifier import deliver, keep_until_dismissed, make_toast  # noqa: E402

URL = "https://montourdumontblanc.com/fr/reservation/refuge-des-mottets/20270610"


class ToastContentTests(unittest.TestCase):
    def test_click_opens_the_reservation_page(self) -> None:
        captured: dict[str, str] = {}

        def run(*, file: str = "", command: str = "") -> None:
            captured["command"] = command

        toast = make_toast(
            "Refuge beds available",
            "Refuge des Mottets has 16 beds on 10/06/2027.",
            URL,
        )
        with patch("notifier._run_ps_checked", run):
            deliver(toast)

        script = captured["command"]
        self.assertIn('scenario="reminder"', script)
        self.assertIn('activationType="protocol"', script)
        self.assertIn(f'launch="{URL}"', script)
        self.assertIn(f'arguments="{URL}"', script)
        self.assertIn("Open booking page", script)
        self.assertIn("Refuge des Mottets has 16 beds on 10/06/2027.", script)

    def test_reminder_marker_is_added_once(self) -> None:
        command = '<toast activationType="protocol" launch="https://example.test" duration="long">'
        once = keep_until_dismissed(command)
        twice = keep_until_dismissed(once)
        self.assertEqual(once, twice)
        self.assertIn('<toast scenario="reminder" ', once)


if __name__ == "__main__":
    unittest.main()
