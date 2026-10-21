# TMB refuge alerts

Windows app that watches the official Tour du Mont-Blanc refuge calendar and shows a notification when a date has enough free beds. It does not log in or book. The notification stays on screen until you close it.

## On another PC

1. Install Python 3.12 from [python.org](https://www.python.org/downloads/windows/). On the first installer screen, turn on **Add python.exe to PATH**.
2. Clone this repo and open a terminal in the folder.
3. Install the one dependency and start the app:

```
python -m pip install -r requirements.txt
pythonw app.py
```

Leave the window open. You can minimize it. Checks stop when you close it. Turn on **Start when I sign in to Windows** if you want it to launch at login.

Your watches are saved in `watches.json` in this folder.

## Email while the PC is off

GitHub can run the same check about every 30 minutes. The job reads the `watches.json` committed on `main`. When a watched date newly has enough beds, it sends one email. A date that stays open does not send again. If it fills and later opens again, that sends a new email. The first run also emails any date that is already open.

In the repo on GitHub, open **Settings → Secrets and variables → Actions** and add:

| Name | Value |
| --- | --- |
| `SMTP_HOST` | `smtp.gmail.com` for Gmail, or `smtp.office365.com` for Outlook |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the mailbox address |
| `SMTP_PASSWORD` | an app password, not the normal mailbox password |
| `ALERT_FROM` | the same mailbox address |
| `ALERT_TO` | who should receive the alert; separate several addresses with commas |

Gmail creates the app password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). Commit and push `watches.json` to `main` before the schedule can see those watches. **Actions → tmb_refuge_alert → Run workflow** sends a check without waiting for the next half hour. Turn on **Send a test email** to confirm the mailbox before a refuge opens.
