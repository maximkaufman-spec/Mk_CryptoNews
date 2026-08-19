#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Крипто-новости -> Telegram bot
Отправляет одну свежую крипто-новость на РУССКОМ в Telegram каждые N минут.

Переменные окружения (Railway -> Variables):
  BOT_TOKEN         - токен бота от @BotFather
  CHAT_ID           - куда слать (узнать у @userinfobot)
  INTERVAL_SECONDS  - (необязательно) интервал в секундах, по умолчанию 120

Только стандартная библиотека Python — pip install не нужен.
"""

import os
import time
import html
import json
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
INTERVAL_SECONDS = int(os.environ.get("INTERVAL_SECONDS", "120"))  # 120 = 2 минуты

# РУССКОЯЗЫЧНЫЕ крипто-новостные RSS-ленты.
FEEDS = [
    "https://ru.cointelegraph.com/rss",   # Cointelegraph на русском
    "https://forklog.com/feed/",          # ForkLog
    "https://bits.media/rss/news/",       # Bits.media
]
# ==================================

USER_AGENT = "Mozilla/5.0 (CryptoNewsBot)"
seen_links = set()  # уже отправленные новости


def fetch_feed(url):
    """Скачивает и парсит одну RSS-ленту, возвращает список (title, link, published)."""
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        for item in root.iter("item"):
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            pub = item.findtext("pubDate", default="").strip()
            if title and link:
                items.append((title, link, pub))
    except Exception as e:
        print(f"[warn] не удалось прочитать ленту {url}: {e}")
    return items


def get_latest_unseen():
    """Собирает новости со всех лент и возвращает самую свежую ещё не отправленную."""
    all_items = []
    for url in FEEDS:
        all_items.extend(fetch_feed(url))
    for title, link, pub in all_items:
        if link not in seen_links:
            return (title, link, pub)
    return None


def send_telegram(text):
    """Отправляет сообщение в Telegram."""
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",
    }).encode()
    req = urllib.request.Request(api, data=payload, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        result = json.loads(resp.read().decode())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result


def format_message(title, link, pub):
    title = html.escape(title)
    msg = f"📰 <b>{title}</b>\n\n🔗 {link}"
    if pub:
        msg += f"\n🕒 {html.escape(pub)}"
    return msg


def main():
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Не заданы BOT_TOKEN и/или CHAT_ID. На Railway добавь их во вкладке Variables.")
        return

    print("✅ Бот запущен. Проверяю связь с Telegram...")
    try:
        send_telegram("🤖 Бот крипто-новостей запущен. Новости будут приходить каждые "
                      f"{INTERVAL_SECONDS // 60} мин.")
        print("✅ Тестовое сообщение отправлено. Погнали!")
    except Exception as e:
        print(f"❌ Не удалось отправить тестовое сообщение. Проверь BOT_TOKEN и CHAT_ID.\n   {e}")
        return

    while True:
        try:
            item = get_latest_unseen()
            if item:
                title, link, pub = item
                send_telegram(format_message(title, link, pub))
                seen_links.add(link)
                print(f"[ok] отправлено: {title}")
                if len(seen_links) > 2000:
                    for old in list(seen_links)[:1000]:
                        seen_links.discard(old)
            else:
                print("[info] новых новостей пока нет, жду следующий цикл.")
        except Exception as e:
            print(f"[error] сбой в цикле: {e}")

        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
