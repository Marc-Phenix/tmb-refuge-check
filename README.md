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
