"""Window for watching several Tour du Mont-Blanc refuge dates."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import date, datetime
from pathlib import Path
from tkinter import messagebox, ttk
from uuid import uuid4

from checker import (
    DEFAULT_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    Watch,
    check_watches,
    fetch_text,
    load_config,
    load_state,
    save_config,
    save_state,
)
from notifier import notify_available, notify_test
from parser import Refuge, parse_refuges, reservation_url

APP_DIR = Path(__file__).resolve().parent
BASE_URL = "https://montourdumontblanc.com"
_mutex_handle = None


class App:
    def __init__(self, data_dir: Path | None = None, *, start_background: bool = True) -> None:
        self.data_dir = data_dir or APP_DIR
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.data_dir / "watches.json"
        self.state_path = self.data_dir / "state.json"
        try:
            self.interval_minutes, self.watches = load_config(self.config_path)
            self.state = load_state(self.state_path)
        except (OSError, ValueError, TypeError, KeyError):
            self.interval_minutes = DEFAULT_INTERVAL_MINUTES
            self.watches = []
            self.state = {}
        self.refuges_by_label: dict[str, Refuge] = {}
        self._lock = threading.Lock()
        self.stop = threading.Event()
        self.wake = threading.Event()

        self.root = tk.Tk()
        self.root.title("TMB refuge alerts")
        self.root.geometry("920x560")
        self.root.minsize(760, 460)
        self._apply_theme()
        self._build()
        self._load_rows()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        if start_background:
            self._start_workers()

    def run(self) -> None:
        self.root.mainloop()

    def on_close(self) -> None:
        self.stop.set()
        self.wake.set()
        self.root.destroy()

    def _apply_theme(self) -> None:
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Treeview", rowheight=26)

    def _build(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(4, weight=1)

        ttk.Label(frame, text="TMB refuge alerts", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            frame,
            text=(
                "Get a Windows notification when a refuge on the official Tour du Mont-Blanc "
                "site has enough free beds. The notification stays on screen until you close it. "
                "This does not log in or book. Leave this window open (you can minimize it); "
                "checks stop when you close it."
            ),
            wraplength=860,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        form = ttk.Frame(frame)
        form.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        today = date.today()
        self.refuge_var = tk.StringVar()
        self.day_var = tk.StringVar(value=str(today.day))
        self.month_var = tk.StringVar(value=str(today.month))
        self.year_var = tk.StringVar(value=str(today.year))
        self.beds_var = tk.StringVar(value="1")
        self.interval_var = tk.StringVar(value=str(self.interval_minutes))
        self.startup_var = tk.BooleanVar(value=startup_enabled())
        self.list_var = tk.StringVar(value="Loading refuges…")
        self.activity_var = tk.StringVar(value="Checks run while this window is open.")

        ttk.Label(form, text="Refuge").grid(row=0, column=0, sticky="w")
        self.refuge_box = ttk.Combobox(
            form, textvariable=self.refuge_var, state="readonly", width=42
        )
        self.refuge_box.grid(row=1, column=0, sticky="w", padx=(0, 10))

        ttk.Label(form, text="Day").grid(row=0, column=1, sticky="w")
        ttk.Spinbox(form, from_=1, to=31, textvariable=self.day_var, width=5).grid(
            row=1, column=1, sticky="w", padx=(0, 6)
        )
        ttk.Label(form, text="Month").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(form, from_=1, to=12, textvariable=self.month_var, width=5).grid(
            row=1, column=2, sticky="w", padx=(0, 6)
        )
        ttk.Label(form, text="Year").grid(row=0, column=3, sticky="w")
        ttk.Spinbox(form, from_=2026, to=2030, textvariable=self.year_var, width=7).grid(
            row=1, column=3, sticky="w", padx=(0, 10)
        )
        ttk.Label(form, text="Min beds").grid(row=0, column=4, sticky="w")
        ttk.Spinbox(form, from_=1, to=30, textvariable=self.beds_var, width=5).grid(
            row=1, column=4, sticky="w", padx=(0, 10)
        )
        self.add_button = ttk.Button(form, text="Add watch", command=self.add_watch)
        self.add_button.grid(row=1, column=5, sticky="sw")
        ttk.Label(form, textvariable=self.list_var).grid(
            row=2, column=0, columnspan=6, sticky="w", pady=(8, 0)
        )

        options = ttk.Frame(frame)
        options.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        ttk.Label(options, text="Check every").pack(side="left")
        interval = ttk.Spinbox(
            options,
            from_=MIN_INTERVAL_MINUTES,
            to=180,
            textvariable=self.interval_var,
            width=5,
            command=self.on_interval,
        )
        interval.pack(side="left", padx=(6, 4))
        interval.bind("<FocusOut>", self.on_interval)
        interval.bind("<Return>", self.on_interval)
        ttk.Label(options, text="minutes").pack(side="left")
        ttk.Checkbutton(
            options,
            text="Start when I sign in to Windows",
            variable=self.startup_var,
            command=self.on_startup,
        ).pack(side="left", padx=(16, 0))
        ttk.Button(options, text="Check now", command=self.check_now).pack(side="right")
        ttk.Button(options, text="Send test notification", command=self.send_test_notification).pack(
            side="right", padx=(0, 8)
        )

        columns = ("refuge", "date", "beds", "status", "checked")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        self.tree.grid(row=4, column=0, sticky="nsew")
        self.tree.heading("refuge", text="Refuge")
        self.tree.heading("date", text="Date")
        self.tree.heading("beds", text="Min beds")
        self.tree.heading("status", text="Status")
        self.tree.heading("checked", text="Last check")
        self.tree.column("refuge", width=280, anchor="w")
        self.tree.column("date", width=110, anchor="w")
        self.tree.column("beds", width=80, anchor="center")
        self.tree.column("status", width=220, anchor="w")
        self.tree.column("checked", width=150, anchor="w")
        self.tree.tag_configure("open", foreground="#0b6e4f")
        self.tree.tag_configure("error", foreground="#9b1c1c")
        self.tree.bind("<Double-1>", self.open_selected)
        self.tree.bind("<Delete>", lambda _event: self.remove_selected())

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Remove selected", command=self.remove_selected).pack(side="left")
        ttk.Button(buttons, text="Open booking page", command=self.open_selected).pack(
            side="left", padx=(8, 0)
        )
        ttk.Label(buttons, textvariable=self.activity_var).pack(side="right")

    def _load_rows(self) -> None:
        for watch in self.watches:
            saved = self.state.get(watch.id, {})
            detail = _saved_detail(saved) if saved else "Not checked yet"
            checked = format_checked(str(saved.get("checked_at", "")))
            self.insert_row(watch, detail, checked, _saved_tags(saved))

    def _start_workers(self) -> None:
        threading.Thread(target=self._load_refuges, name="tmb-refuges", daemon=True).start()
        threading.Thread(target=self._loop, name="tmb-checks", daemon=True).start()
        ensure_launcher_shortcut()

    def _load_refuges(self) -> None:
        try:
            refuges = parse_refuges(fetch_text(f"{BASE_URL}/fr/refuges"))
        except Exception as exc:
            self.root.after(0, lambda: self.list_var.set(f"Could not load refuges: {exc}"))
            return
        self.root.after(0, lambda: self._set_refuges(refuges))

    def _set_refuges(self, refuges: list[Refuge]) -> None:
        labels: list[str] = []
        used: set[str] = set()
        mapping: dict[str, Refuge] = {}
        for refuge in refuges:
            label = refuge.name
            if label in used:
                label = f"{refuge.name} ({refuge.slug})"
            used.add(label)
            mapping[label] = refuge
            labels.append(label)
        self.refuges_by_label = mapping
        self.refuge_box["values"] = labels
        if labels and not self.refuge_var.get():
            self.refuge_box.current(0)
        self.list_var.set(f"{len(labels)} refuges loaded from the official site.")

    def _loop(self) -> None:
        while not self.stop.is_set():
            self.run_check()
            if self.stop.is_set():
                break
            self.wake.wait(self.interval_minutes * 60)
            self.wake.clear()

    def check_now(self) -> None:
        self.activity_var.set("Checking the official calendar…")
        self.wake.set()

    def send_test_notification(self) -> None:
        self.activity_var.set("Sending a test notification…")
        threading.Thread(target=self._send_test, name="tmb-test-toast", daemon=True).start()

    def _send_test(self) -> None:
        try:
            notify_test(f"{BASE_URL}/fr/refuges")
        except Exception as exc:
            self.root.after(0, lambda: self.activity_var.set(f"Test notification failed: {exc}"))
            return
        self.root.after(
            0,
            lambda: self.activity_var.set("Test notification sent. It stays until you close it."),
        )

    def run_check(self) -> None:
        with self._lock:
            watches = list(self.watches)
            previous = dict(self.state)
        if not watches:
            self.root.after(0, lambda: self.activity_var.set("No watches yet. Add a refuge and a date."))
            return
        self.root.after(0, lambda: self.activity_var.set("Checking the official calendar…"))
        try:
            results, new_state = check_watches(watches, previous)
        except Exception as exc:
            self.root.after(0, lambda: self.activity_var.set(f"Check failed: {exc}"))
            return

        with self._lock:
            current_ids = {watch.id for watch in self.watches}
            for watch_id, payload in new_state.items():
                if watch_id in current_ids:
                    self.state[watch_id] = payload
            self.state = {key: value for key, value in self.state.items() if key in current_ids}
            save_state(self.state_path, self.state)
            current = {watch.id: watch for watch in self.watches}

        problems: list[str] = []
        for result in results:
            watch = current.get(result.watch_id)
            if watch is None or not result.should_notify:
                continue
            try:
                notify_available(watch.name, watch.date, result.beds or 0, result.url)
            except Exception as exc:
                problems.append(str(exc))
        when = format_checked(results[0].checked_at)
        summary = f"Last check {when}."
        if problems:
            summary = f"{summary} Notification failed: {problems[0]}"
        self.root.after(0, lambda results=results, summary=summary: self.apply_results(results, summary))

    def apply_results(self, results, summary: str) -> None:
        by_id = {watch.id: watch for watch in self.watches}
        for result in results:
            watch = by_id.get(result.watch_id)
            if watch is None or not self.tree.exists(result.watch_id):
                continue
            tags = ("error",) if result.status == "error" else (("open",) if result.is_open else ())
            self.tree.item(
                result.watch_id,
                values=row_values(watch, result.detail, format_checked(result.checked_at)),
                tags=tags,
            )
        self.activity_var.set(summary)

    def add_watch(self) -> None:
        label = self.refuge_var.get().strip()
        refuge = self.refuges_by_label.get(label)
        if refuge is None:
            messagebox.showwarning("Refuge", "Choose a refuge from the list.", parent=self.root)
            return
        try:
            chosen = date(int(self.year_var.get()), int(self.month_var.get()), int(self.day_var.get()))
        except ValueError:
            messagebox.showwarning("Date", "That date does not exist.", parent=self.root)
            return
        try:
            min_beds = int(self.beds_var.get())
        except ValueError:
            messagebox.showwarning("Beds", "Enter how many beds you need.", parent=self.root)
            return
        if min_beds < 1:
            messagebox.showwarning("Beds", "Ask for at least 1 bed.", parent=self.root)
            return
        for watch in self.watches:
            if watch.slug == refuge.slug and watch.date == chosen:
                messagebox.showinfo(
                    "Already watching",
                    "That refuge and date are already in the list. Remove it to change the number of beds.",
                    parent=self.root,
                )
                return
        watch = Watch(
            id=uuid4().hex,
            slug=refuge.slug,
            name=refuge.name,
            date=chosen,
            min_beds=min_beds,
        )
        with self._lock:
            self.watches.append(watch)
            save_config(self.config_path, self.interval_minutes, self.watches)
        self.insert_row(watch, "Not checked yet", "")
        self.wake.set()

    def remove_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        with self._lock:
            remove_ids = set(selected)
            self.watches = [watch for watch in self.watches if watch.id not in remove_ids]
            for watch_id in remove_ids:
                self.state.pop(watch_id, None)
            save_config(self.config_path, self.interval_minutes, self.watches)
            save_state(self.state_path, self.state)
        for watch_id in selected:
            if self.tree.exists(watch_id):
                self.tree.delete(watch_id)

    def open_selected(self, _event=None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        watch = next((item for item in self.watches if item.id == selected[0]), None)
        if watch is not None:
            webbrowser.open(reservation_url(watch.slug, watch.date))

    def on_interval(self, _event=None) -> None:
        try:
            value = int(self.interval_var.get())
        except ValueError:
            self.interval_var.set(str(self.interval_minutes))
            return
        value = min(180, max(MIN_INTERVAL_MINUTES, value))
        self.interval_minutes = value
        self.interval_var.set(str(value))
        with self._lock:
            save_config(self.config_path, self.interval_minutes, self.watches)

    def on_startup(self) -> None:
        try:
            set_startup(bool(self.startup_var.get()))
        except Exception as exc:
            self.startup_var.set(startup_enabled())
            messagebox.showerror(
                "Startup",
                f"Could not update the Startup shortcut.\n{exc}",
                parent=self.root,
            )

    def insert_row(self, watch: Watch, detail: str, checked: str, tags: tuple[str, ...] = ()) -> None:
        self.tree.insert(
            "",
            "end",
            iid=watch.id,
            values=row_values(watch, detail, checked),
            tags=tags,
        )


def row_values(watch: Watch, detail: str, checked: str) -> tuple[str, str, str, str, str]:
    return (watch.name, watch.date.strftime("%d/%m/%Y"), str(watch.min_beds), detail, checked)


def format_checked(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.strftime("%d/%m/%Y %H:%M")


def _saved_detail(saved: dict) -> str:
    status = saved.get("status")
    if status == "error":
        return f"Error: {saved.get('error') or 'check failed'}"
    if status == "available" and saved.get("open"):
        beds = saved.get("beds")
        noun = "bed" if beds == 1 else "beds"
        return f"Open, {beds} {noun}"
    if status == "available":
        return f"{saved.get('beds') or 0} beds, below your minimum"
    if status == "full":
        return "Full"
    if status == "closed":
        return "Closed"
    if status == "missing":
        return "Date not on calendar"
    if status == "past":
        return "Past"
    return "Not checked yet"


def _saved_tags(saved: dict) -> tuple[str, ...]:
    if saved.get("status") == "error":
        return ("error",)
    if saved.get("open"):
        return ("open",)
    return ()


def startup_shortcut_path() -> Path:
    appdata = Path(os.environ["APPDATA"])
    return appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "TMB Refuge Watch.lnk"


def launcher_shortcut_path() -> Path:
    return APP_DIR / "TMB refuge alerts.lnk"


def startup_enabled() -> bool:
    return startup_shortcut_path().exists()


def set_startup(enabled: bool) -> None:
    path = startup_shortcut_path()
    if not enabled:
        path.unlink(missing_ok=True)
        return
    write_shortcut(path)


def ensure_launcher_shortcut() -> None:
    try:
        write_shortcut(launcher_shortcut_path())
    except Exception:
        return


def write_shortcut(path: Path) -> None:
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        pythonw = Path(sys.executable)
    script = str(APP_DIR / "app.py")
    command = r"""
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($env:TMB_SHORTCUT)
$link.TargetPath = $env:TMB_PYTHONW
$link.Arguments = '"' + $env:TMB_SCRIPT + '"'
$link.WorkingDirectory = $env:TMB_WORKDIR
$link.Description = 'TMB refuge availability alerts'
$link.Save()
"""
    env = os.environ.copy()
    env["TMB_SHORTCUT"] = str(path)
    env["TMB_PYTHONW"] = str(pythonw)
    env["TMB_SCRIPT"] = script
    env["TMB_WORKDIR"] = str(APP_DIR)
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Could not create the shortcut.").strip()
        raise RuntimeError(detail)


def acquire_single_instance() -> bool:
    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    ctypes.set_last_error(0)
    _mutex_handle = kernel32.CreateMutexW(None, False, "Local\\TMBRefugeWatch")
    return ctypes.get_last_error() != 183


def main() -> None:
    if not acquire_single_instance():
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("TMB refuge alerts", "TMB refuge alerts is already running.")
        root.destroy()
        return
    App().run()


if __name__ == "__main__":
    main()
