"""Email when a watched refuge date newly has enough beds."""

from __future__ import annotations

import os
import smtplib
import sys
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

from checker import Watch, WatchStatus, check_watches, fetch_text, load_config, load_state, save_state

MAIL_SETTING_NAMES = (
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "ALERT_FROM",
    "ALERT_TO",
)


@dataclass(frozen=True)
class MailSettings:
    host: str
    port: int
    user: str
    password: str
    sender: str
    recipients: tuple[str, ...]


def load_mail_settings(env: dict[str, str] | None = None) -> MailSettings:
    source = os.environ if env is None else env
    missing = [name for name in MAIL_SETTING_NAMES if not str(source.get(name, "")).strip()]
    if missing:
        raise RuntimeError("Missing email settings: " + ", ".join(missing))
    recipients = tuple(
        part.strip()
        for part in str(source["ALERT_TO"]).replace(";", ",").split(",")
        if part.strip()
    )
    if not recipients:
        raise RuntimeError("Missing email settings: ALERT_TO")
    try:
        port = int(str(source["SMTP_PORT"]).strip())
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT must be a number.") from exc
    return MailSettings(
        host=str(source["SMTP_HOST"]).strip(),
        port=port,
        user=str(source["SMTP_USER"]).strip(),
        password=str(source["SMTP_PASSWORD"]).strip(),
        sender=str(source["ALERT_FROM"]).strip(),
        recipients=recipients,
    )


def pending_alerts(results: list[WatchStatus]) -> list[WatchStatus]:
    return [result for result in results if result.should_notify]


def build_message(watches: list[Watch], alerts: list[WatchStatus]) -> tuple[str, str]:
    by_id = {watch.id: watch for watch in watches}
    blocks: list[str] = []
    for alert in alerts:
        watch = by_id[alert.watch_id]
        blocks.append(
            "\n".join(
                (
                    _one_line(watch.name),
                    watch.date.strftime("%d/%m/%Y"),
                    _one_line(alert.detail),
                    alert.url,
                )
            )
        )
    body = (
        "A watched Tour du Mont-Blanc date has enough free beds.\n\n"
        + "\n\n".join(blocks)
        + "\n\nThis check does not log in or book."
    )
    if len(alerts) == 1:
        watch = by_id[alerts[0].watch_id]
        subject = f"TMB refuge open: {_one_line(watch.name)} {watch.date.strftime('%d/%m/%Y')}"
    else:
        subject = f"TMB refuges open ({len(alerts)})"
    return subject, body


def send_email(settings: MailSettings, subject: str, body: str) -> None:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.sender
    message["To"] = ", ".join(settings.recipients)
    message.set_content(body)
    try:
        if settings.port == 465:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=30, local_hostname="localhost") as smtp:
                _login(smtp, settings)
                smtp.send_message(message)
            return
        with smtplib.SMTP(settings.host, settings.port, timeout=30, local_hostname="localhost") as smtp:
            smtp.ehlo("localhost")
            smtp.starttls()
            smtp.ehlo("localhost")
            _login(smtp, settings)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError("Gmail did not accept the mailbox address or app password.") from exc
    except smtplib.SMTPServerDisconnected as exc:
        raise RuntimeError(
            "Gmail closed the connection during login. Check the mailbox address and app password."
        ) from exc


def _login(smtp: smtplib.SMTP, settings: MailSettings) -> None:
    # One method so a rejected password stays a clear auth error. Gmail
    # hangs up if the client tries a second method after the first failure.
    if "auth" in smtp.esmtp_features:
        smtp.esmtp_features["auth"] = "PLAIN"
    smtp.login(settings.user, settings.password)


def open_flags(state: dict) -> dict:
    flags: dict[str, dict] = {}
    for watch_id, payload in state.items():
        if isinstance(payload, dict):
            flags[str(watch_id)] = {"open": bool(payload.get("open"))}
    return flags


def run(
    config_path: Path,
    state_path: Path,
    *,
    fetch=fetch_text,
    send=None,
) -> None:
    """Check the watches and email only for dates that newly opened.

    State is saved after a successful check. When an email is required, a
    failed send leaves the previous state in place so the next run tries again.
    """
    _interval, watches = load_config(config_path)
    previous = load_state(state_path)
    if not watches:
        _save_if_changed(state_path, previous, {})
        print("No watches in watches.json.")
        return

    results, new_state = check_watches(watches, previous, fetch=fetch)
    alerts = pending_alerts(results)
    if alerts:
        subject, body = build_message(watches, alerts)
        deliver = send or _deliver
        deliver(subject, body)
        print(f"Sent an email for {len(alerts)} opening(s).")
    else:
        print("No new openings.")
    _save_if_changed(state_path, previous, new_state)


def _deliver(subject: str, body: str) -> None:
    send_email(load_mail_settings(), subject, body)


def _save_if_changed(path: Path, previous: dict, new_state: dict) -> None:
    updated = open_flags(new_state)
    if updated == open_flags(previous):
        return
    save_state(path, updated)


def _one_line(value: str) -> str:
    return " ".join(value.split())


def send_test() -> None:
    send_email(
        load_mail_settings(),
        "TMB refuge alerts are on",
        "This mailbox will get a message when a watched refuge date newly has enough free beds.\n\n"
        "This check does not log in or book.",
    )
    print("Sent a test email.")


def main() -> None:
    root = Path(__file__).resolve().parent
    try:
        if os.environ.get("TMB_SEND_TEST", "").strip().lower() in {"1", "true"}:
            send_test()
        run(root / "watches.json", root / "alert-state.json")
    except Exception as exc:
        print(f"Alert check failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
