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
STATE_DIR_ENV = "RADAR_STATE_DIR"  # homelab worker keeps delivery state outside the clone
LOCAL_TZ = ZoneInfo("Europe/Istanbul")
MAX_REMEMBERED = 3000
TELEGRAM_LIMIT = 4096
LANE_HEADINGS = {
    "model": "🧠 Yeni modeller",
    "paper": "📄 Paper'lar",
    "repo": "🧰 Repolar",
    "news": "📰 Haberler",
}
# Telegram shows the top of each lane; the site and RSS carry everything.
DIGEST_PER_LANE = {"model": 6, "paper": 5, "repo": 5, "news": 8}
TITLE_LIMIT = 70
TURKISH_MONTHS = (
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
)
SOURCE_NAMES = {
    "openai-news": "OpenAI",
    "deepmind-blog": "Google DeepMind",
    "google-ai-blog": "Google",
    "mistral-news": "Mistral",
    "nvidia-dev-blog": "NVIDIA",
    "msr-blog": "Microsoft Research",
    "github-blog-ai": "GitHub",
    "simonwillison": "Simon Willison",
    "latent-space": "Latent Space",
    "hf-blog": "Hugging Face",
    "vllm-blog": "vLLM",
    "ollama-blog": "Ollama",
    "hn-llm-top": "Hacker News",
    "hn-vllm": "Hacker News",
    "hn-ollama": "Hacker News",
    "hn-llamacpp": "Hacker News",
}


class TelegramError(RuntimeError):
    """Delivery failed; the message never contains the bot token."""


def telegram_credentials(root: Path | None = None) -> tuple[str, str] | None:
    _load_dotenv(root)
    token = os.environ.get(TOKEN_ENV, "").strip()
    chat = os.environ.get(CHAT_ENV, "").strip()
    return (token, chat) if token and chat else None


def state_file(root: Path, default: Path) -> Path:
    """``$RADAR_STATE_DIR/<name>`` when set, else ``root/default``.

    The homelab worker's repo clone is disposable (``git pull`` only); its
    delivery and alert state must survive re-clones and never collide with a
    tracked file, so it lives in /var/lib/radar there.
    """
    state_dir = os.environ.get(STATE_DIR_ENV, "").strip()
    return Path(state_dir) / default.name if state_dir else root / default


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
    per_lane: dict[str, int] | None = None,
) -> list[DigestMessage]:
    """A short, scannable digest; [] if nothing new.

    The first live digest (2026-09-30) listed all 630 new items in 22
    messages and the owner found it unreadable. Telegram now carries the top
    ``per_lane`` items of each lane as numbered one-liners; the rest are
    counted ("+N more on the site") and still recorded as delivered so they
    never pile up. The site and RSS keep everything ("I want all").

    Messages stay under Telegram's 4096-char limit; if the capped digest is
    still too long, it splits without breaking an item, and every message
    knows its item ids so delivery is recorded per message sent.
    """
    if not any(picks.values()):
        return []
    caps = per_lane or DIGEST_PER_LANE
    total_new = sum(len(rows) for rows in picks.values())
    lines = [f"🛰️ <b>AI Radar Pulse</b> · {_turkish_date(today)}"]
    if view["health"].get("degraded"):
        lines.append("⚠️ <i>Sıralama bugün yedek kurallarla yapıldı (Jev'e ulaşılamadı).</i>")

    chunks: list[tuple[list[str], list[str]]] = []
    ids: list[str] = []
    for lane, rows in picks.items():
        if not rows:
            continue
        shown, rest = rows[: caps.get(lane, 5)], rows[caps.get(lane, 5):]
        heading = f"<b>{LANE_HEADINGS[lane]}</b> <i>({len(rows)} yeni)</i>"
        lines += ["", heading]
        for number, row in enumerate(shown, start=1):
            line = _item_line(number, row)
            if len("\n".join([*lines, line])) > TELEGRAM_LIMIT - 16:  # room for "(n/N)"
                chunks.append((lines, ids))
                lines, ids = [f"{heading} (devam)"], []
            lines.append(line)
            ids.append(row["id"])
        if rest:
            lines.append(f"<i>+{len(rest)} daha sitede</i>")
            ids.extend(row["id"] for row in rest)  # seen via the site; never re-sent
    if site_url:
        site = escape(site_url, quote=True)
        rss = escape(site_url.rstrip("/") + "/pulse.xml", quote=True)
        footer = f'Tümü ({total_new} yeni öğe): <a href="{site}">site</a> · <a href="{rss}">RSS</a>'
        if len("\n".join([*lines, "", footer])) <= TELEGRAM_LIMIT - 16:
            lines += ["", footer]
    chunks.append((lines, ids))
    total = len(chunks)
    return [
        DigestMessage(
            text=("\n".join(chunk) if total == 1 or i == 1 else f"({i}/{total})\n" + "\n".join(chunk)),
            item_ids=tuple(chunk_ids),
        )
        for i, (chunk, chunk_ids) in enumerate(chunks, start=1)
    ]


def _item_line(number: int, row: dict[str, Any]) -> str:
    """``1. <link>Short title</link> · owner · signal`` — one line, no raw URLs."""
    title = str(row["title"])
    owner = ""
    if row["lane"] in ("model", "repo") and "/" in title:
        owner, title = title.split("/", 1)
    parts = [f'<a href="{escape(row["url"], quote=True)}">{escape(_shorten(title))}</a>']
    parts += [escape(part) for part in (owner, _signal(row)) if part]
    return f"{number}. " + " · ".join(parts)


def _shorten(text: str, limit: int = TITLE_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _signal(row: dict[str, Any]) -> str:
    """The one number that says why this item is here."""
    signals = row.get("signals") or {}
    lane = row["lane"]
    if lane == "model" and signals.get("likes"):
        return f"♥ {int(signals['likes'])}"
    if lane == "paper":
        upvotes = f"▲ {int(signals.get('upvotes', 0))}"
        return upvotes + (" · kod" if signals.get("has_code") else "")
    if lane == "repo" and signals.get("stars_per_day"):
        return f"★ {round(signals['stars_per_day'])}/gün"
    if lane == "news":
        return SOURCE_NAMES.get(str(row.get("source", "")), str(row.get("source", "")))
    return ""


def _turkish_date(day: date) -> str:
    return f"{day.day} {TURKISH_MONTHS[day.month - 1]} {day.year}"


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
