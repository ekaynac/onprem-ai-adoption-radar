"""Daily Pulse digest to Telegram, exactly once per item.

Sent from the owner's existing radar bot (Memati) via the Bot API
``sendMessage``; this never polls, so it cannot fight the openclaw gateway
that reads the same bot's updates.

The bot token sits inside the request URL (``/bot<token>/sendMessage``), and
httpx puts URLs in both exception text and INFO logs. Errors are therefore
rewritten without the URL, and the httpx logger is raised to WARNING before
any call.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from radar.huggingface_auth import _load_dotenv


TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
CHAT_ENV = "TELEGRAM_CHAT_ID"
STATE_PATH = Path("data") / "pulse" / "telegram-state.json"
LOCAL_TZ = ZoneInfo("Europe/Istanbul")
MAX_REMEMBERED = 3000
TELEGRAM_LIMIT = 4096
LANE_HEADINGS = {
    "model": "🧠 Yeni modeller",
    "paper": "📄 Paper'lar",
    "repo": "🧰 Repolar",
    "news": "📰 Haberler",
}


class TelegramError(RuntimeError):
    """Delivery failed; the message never contains the bot token."""


def telegram_credentials(root: Path | None = None) -> tuple[str, str] | None:
    _load_dotenv(root)
    token = os.environ.get(TOKEN_ENV, "").strip()
    chat = os.environ.get(CHAT_ENV, "").strip()
    return (token, chat) if token and chat else None


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"last_sent_date": None, "delivered": []}
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or not isinstance(state.get("delivered"), list):
        raise ValueError(f"{path}: malformed Telegram delivery state")
    return state


def select_new(view: dict[str, Any], delivered: set[str]) -> dict[str, list[dict[str, Any]]]:
    """Every undelivered TOP item per lane, in rank order (no cap: owner wants all)."""
    return {
        section["lane"]: [r for r in section["items"] if r["id"] not in delivered]
        for section in view["lanes"]
    }


@dataclass(frozen=True)
class DigestMessage:
    text: str
    item_ids: tuple[str, ...]


def render_digest(
    picks: dict[str, list[dict[str, Any]]],
    view: dict[str, Any],
    site_url: str,
    today: date,
) -> list[DigestMessage]:
    """The digest as Telegram-sized messages (each <= 4096 chars); [] if nothing new.

    Items are never split across messages: a message closes before the item
    that would overflow it and the lane heading repeats on the next one. Each
    message knows its item ids so delivery is recorded per message sent.
    """
    if not any(picks.values()):
        return []
    lines = [f"🛰️ <b>AI Radar Pulse</b> — {today.isoformat()}"]
    if view["health"].get("degraded"):
        lines.append("⚠️ <i>Triage degraded: most items were ranked by rules, not Jev.</i>")
    footer = [f'<a href="{escape(site_url, quote=True)}">Full list and RSS</a>'] if site_url else []

    chunks: list[tuple[list[str], list[str]]] = []
    ids: list[str] = []
    for lane, rows in picks.items():
        if not rows:
            continue
        heading = f"<b>{LANE_HEADINGS[lane]}</b>"
        lines += ["", heading]
        for row in rows:
            line = _item_line(row)
            if len("\n".join([*lines, line])) > TELEGRAM_LIMIT - 16:  # room for "(n/N)"
                chunks.append((lines, ids))
                lines, ids = [f"{heading} (continued)"], []
            lines.append(line)
            ids.append(row["id"])
    if footer and len("\n".join([*lines, "", *footer])) <= TELEGRAM_LIMIT - 16:
        lines += ["", *footer]
    chunks.append((lines, ids))
    total = len(chunks)
    return [
        DigestMessage(
            text=("\n".join(chunk) if total == 1 or i == 1 else f"({i}/{total})\n" + "\n".join(chunk)),
            item_ids=tuple(chunk_ids),
        )
        for i, (chunk, chunk_ids) in enumerate(chunks, start=1)
    ]


def _item_line(row: dict[str, Any]) -> str:
    detail = _detail(row)
    line = (f'• <a href="{escape(row["url"], quote=True)}">{escape(row["title"])}</a>'
            + (f" — {escape(detail)}" if detail else ""))
    return line[: TELEGRAM_LIMIT - 200]


async def send_message(client: Any, token: str, chat_id: str, text: str) -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    try:
        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
        )
        payload = response.json()
    except Exception as exc:
        raise TelegramError(f"Telegram request failed: {type(exc).__name__}") from None
    if response.status_code != 200 or not payload.get("ok"):
        description = str(payload.get("description", "unknown error")).replace(token, "***")
        raise TelegramError(f"Telegram rejected the message ({response.status_code}): {description}")


def record_delivery(state: dict[str, Any], sent_ids: list[str]) -> dict[str, Any]:
    """Remember delivered ids (bounded); the send date is set separately."""
    delivered = [*state.get("delivered", []), *sent_ids][-MAX_REMEMBERED:]
    return {**state, "delivered": delivered}


def mark_sent(state: dict[str, Any], today: date) -> dict[str, Any]:
    """Only once every message of the digest went out, so a partial failure retries today."""
    return {**state, "last_sent_date": today.isoformat()}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
    tmp.replace(path)


def local_today(now: datetime) -> date:
    return now.astimezone(LOCAL_TZ).date()


def _detail(row: dict[str, Any]) -> str:
    """One compact signal per line: likes for models, upvotes/velocity, news source."""
    reasons = row.get("reasons") or []
    if row["lane"] == "news":
        return str(row.get("source", ""))
    if row["lane"] == "model":
        return str(reasons[-1]) if reasons else ""
    return str(reasons[0]) if reasons else ""
