"""Windows toast notifications that open the official booking page."""

from __future__ import annotations

import subprocess
import threading
from datetime import date

import winotify
from winotify import Notification, audio

APP_ID = "TMB Refuge Watch"
_toast_lock = threading.Lock()


def make_toast(
    title: str,
    message: str,
    url: str,
    *,
    action_label: str = "Open booking page",
) -> Notification:
    toast = Notification(
        app_id=APP_ID,
        title=title,
        msg=message,
        duration="long",
        launch=url,
    )
    toast.set_audio(audio.Default, loop=False)
    if url:
        toast.add_actions(action_label, url)
    return toast


def notify_available(name: str, day: date, beds: int, url: str) -> None:
    noun = "bed" if beds == 1 else "beds"
    deliver(
        make_toast(
            "Refuge beds available",
            f"{name} has {beds} {noun} on {day:%d/%m/%Y}.",
            url,
        )
    )


def notify_test(url: str) -> None:
    deliver(
        make_toast(
            "TMB refuge alerts test",
            "This stays on screen until you close it. Alerts are working.",
            url,
            action_label="Open the refuge list",
        )
    )


def keep_until_dismissed(command: str) -> str:
    """Ask Windows to leave the toast up until the user closes it."""
    if 'scenario="reminder"' in command:
        return command
    return command.replace("<toast ", '<toast scenario="reminder" ', 1)


def deliver(toast: Notification) -> None:
    """Show a winotify toast and surface PowerShell failures."""
    script: dict[str, str] = {}

    def capture(*, file: str = "", command: str = "") -> None:
        script["command"] = keep_until_dismissed(command)

    with _toast_lock:
        original = winotify._run_ps
        winotify._run_ps = capture
        try:
            toast.show()
        finally:
            winotify._run_ps = original
    _run_ps_checked(command=script.get("command", ""))


def _run_ps_checked(*, file: str = "", command: str = "") -> None:
    if file or not command:
        raise RuntimeError("The notification must be a PowerShell command.")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        capture_output=True,
        text=True,
        timeout=40,
        startupinfo=startup,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "PowerShell could not show the notification").strip()
        raise RuntimeError(detail)
