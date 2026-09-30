#!/usr/bin/env python3
"""OnFailure hook for radar-worker.service: tell the owner the worker broke.

Standard library only, so it still works when the radar environment itself
is what broke. The bot token is read from the environment and sent in the
request URL only; it is never printed, logged or placed on a command line.
"""

import json
import os
import sys
import urllib.request


def main() -> int:
    token = os.environ.get("TELEGRAM_ALERT_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    unit = sys.argv[1] if len(sys.argv) > 1 else "radar-worker.service"
    if not token or not chat_id:
        print("notify-failure: Telegram credentials missing; cannot alert", file=sys.stderr)
        return 1
    text = (
        "🛡️ <b>Radar watchdog</b>\n🔴 ct-radar: "
        f"{unit} failed. Check: <code>journalctl -u {unit} -n 50</code>"
    )
    body = json.dumps({"chat_id": chat_id, "text": text, "parse_mode": "HTML"}).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            ok = json.load(response).get("ok", False)
    except Exception as exc:  # never echo the URL: it carries the token
        print(f"notify-failure: Telegram request failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
