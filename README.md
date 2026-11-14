# YouTube Live Chat Sender

Automation tool for sending recurring live chat messages to YouTube streams via Chrome DevTools Protocol (CDP) on port 9222. Runs in the background without stealing OS focus or interrupting other tasks.

Supports both a terminal runner (`main.py`) and a desktop UI (`gui.py`).

---

## Features

- **Background Execution**: Runs via CDP without moving the mouse or interrupting foreground applications.
- **Multi-Tab Support**: Cycles through multiple open streams with distinct messages per tab.
- **Config Hot-Reload**: Changes to `config.json` take effect immediately at runtime without restarting.
- **Template Variables**: Supports `{uid}` and other custom variables defined in `config.json`.
- **Runtime Hotkeys**: Adjust delays (`+`/`-`) and typing speed (`[`/`]`) directly from the terminal.
- **Error Handling**: Reads slow-mode countdowns and pauses until the timer expires.
- **Log Rotation**: Logs to `logs/run.log`, capped at 5 MB with 3 backups.

---

## Quick Start

### 1. Launch Chrome
Run `start_chrome.bat`:
- Launches Chrome on port 9222 with background throttling disabled.
- Profile is stored in `%LOCALAPPDATA%\yt_bot_profile` (or `C:\yt_bot_profile` if it already exists).
- Log into YouTube and open the target live stream.

### 2. Configure Settings
Edit `config.json`:
```json
{
  "cdp_url": "http://127.0.0.1:9222",
  "delay_ms": 3500,
  "typing_speed_ms": 0,
  "jitter_ms": 200,
  "variables": {
    "uid": "YOUR_UID_HERE"
  },
  "tabs": [
    {
      "name": "Tab 1",
      "tab_url_contains": "https://www.youtube.com/watch",
      "enabled": true,
      "messages": [
        "Giveaway entry! UID: {uid}",
        "Watching stream, 1 RP please! UID: {uid}"
      ]
    }
  ]
}
```

### 3. Start Sending
- **Terminal**: Run `run.bat` (or `python main.py`)
- **Desktop UI**: Run `run_ui.bat` (or `python gui.py`)

---

## Terminal Hotkeys

| Key | Action |
| :---: | :--- |
| `+` / `=` | Decrease delay by 100ms (faster) |
| `-` / `_` | Increase delay by 100ms (slower) |
| `[` | Decrease typing delay by 1ms (faster typing) |
| `]` | Increase typing delay by 1ms (slower typing) |
| `p` | Pause / resume |
| `q` | Safe quit |

---

## Safe Delay Guidelines

YouTube live chat has server-side rate limits. Sending too fast (e.g. < 2 seconds) will cause YouTube to silently drop messages (shadow-filtering):
- **Recommended Delay**: `3000ms` to `6000ms` (3 to 6 seconds).
- **Typing Speed**: `0` for instant insertion, or `3-8ms` for character-by-character typing.
