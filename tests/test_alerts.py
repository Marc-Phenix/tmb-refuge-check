"""Email goes out once when a watched date newly has enough beds."""

from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from checker import Watch, classify_watch, load_state, save_config, save_state  # noqa: E402
from parser import Night  # noqa: E402
from send_alerts import build_message, load_mail_settings, run  # noqa: E402

WATCH = Watch(
    id="mottets-2027-06-10",
    slug="refuge-des-mottets",
    name="Refuge des Mottets",
    date=date(2027, 6, 10),
    min_beds=2,
)
CALENDAR = (ROOT / "tests" / "fixtures" / "calendar_snippet.html").read_text(encoding="utf-8")


def fetch_calendar(url: str) -> str:
    if url.endswith("/refuge-des-mottets"):
        return CALENDAR
    return "<div></div>"


def fetch_down(_url: str) -> str:
    raise TimeoutError("timed out")


class MailSettingsTests(unittest.TestCase):
    def test_splits_several_recipients(self) -> None:
        settings = load_mail_settings(
            {
                "SMTP_HOST": "smtp.example.com",
                "SMTP_PORT": "587",
                "SMTP_USER": "watch@example.com",
                "SMTP_PASSWORD": "secret",
                "ALERT_FROM": "watch@example.com",
                "ALERT_TO": "me@example.com, friend@example.com",
            }
        )
        self.assertEqual(settings.recipients, ("me@example.com", "friend@example.com"))
        self.assertEqual(settings.port, 587)

    def test_missing_settings_are_named(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            load_mail_settings({})
        self.assertIn("ALERT_TO", str(caught.exception))
        self.assertIn("SMTP_PASSWORD", str(caught.exception))


class BuildMessageTests(unittest.TestCase):
    def test_names_the_refuge_and_booking_link(self) -> None:
        subject, body = build_message([WATCH], [_status()])
        self.assertEqual(subject, "TMB refuge open: Refuge des Mottets 10/06/2027")
        self.assertIn("Open, 16 beds", body)
        self.assertIn("/fr/reservation/refuge-des-mottets/20270610", body)


class RunAlertTests(unittest.TestCase):
    def test_first_open_sends_and_remembers(self) -> None:
        sent: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, state = root / "watches.json", root / "alert-state.json"
            save_config(config, 15, [WATCH])
            run(config, state, fetch=fetch_calendar, send=_record(sent))
            self.assertEqual(len(sent), 1)
            self.assertIn("Refuge des Mottets", sent[0][0])
            self.assertTrue(load_state(state)[WATCH.id]["open"])

    def test_still_open_stays_quiet(self) -> None:
        sent: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, state = root / "watches.json", root / "alert-state.json"
            save_config(config, 15, [WATCH])
            save_state(state, {WATCH.id: {"open": True}})
            run(config, state, fetch=fetch_calendar, send=_record(sent))
            self.assertEqual(sent, [])
            self.assertTrue(load_state(state)[WATCH.id]["open"])

    def test_failed_download_does_not_send(self) -> None:
        sent: list[tuple[str, str]] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, state = root / "watches.json", root / "alert-state.json"
            save_config(config, 15, [WATCH])
            run(config, state, fetch=fetch_down, send=_record(sent))
            self.assertEqual(sent, [])
            self.assertFalse(load_state(state)[WATCH.id]["open"])

    def test_failed_send_does_not_remember_the_opening(self) -> None:
        def fail(_subject: str, _body: str) -> None:
            raise RuntimeError("smtp down")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, state = root / "watches.json", root / "alert-state.json"
            save_config(config, 15, [WATCH])
            with self.assertRaises(RuntimeError):
                run(config, state, fetch=fetch_calendar, send=fail)
            self.assertFalse(state.exists())

    def test_reopening_sends_again(self) -> None:
        sent: list[tuple[str, str]] = []
        full = Watch(WATCH.id, WATCH.slug, WATCH.name, date(2027, 6, 24), 1)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config, state = root / "watches.json", root / "alert-state.json"
            save_config(config, 15, [full])
            save_state(state, {full.id: {"open": True}})
            run(config, state, fetch=fetch_calendar, send=_record(sent))
            self.assertEqual(sent, [])
            self.assertFalse(load_state(state)[full.id]["open"])
            save_config(config, 15, [WATCH])
            run(config, state, fetch=fetch_calendar, send=_record(sent))
            self.assertEqual(len(sent), 1)
            self.assertTrue(load_state(state)[WATCH.id]["open"])


def _record(sent: list[tuple[str, str]]):
    def send(subject: str, body: str) -> None:
        sent.append((subject, body))

    return send


def _status():
    return classify_watch(
        WATCH,
        Night(date=WATCH.date, status="available", beds=16),
        previous_open=False,
    )


if __name__ == "__main__":
    unittest.main()
