#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Крипто-новости -> Telegram bot
Отправляет ТОП-10 свежих крипто-новостей на русском 3 раза в день:
в 10:00, 15:00 и 18:00 по киевскому времени.

Переменные окружения (Railway -> Variables):
  BOT_TOKEN         - токен бота от @BotFather
  CHAT_ID           - куда слать (узнать у @userinfobot)
  SEND_TIMES        - (необязательно) время рассылки, напр. "10:00,15:00,18:00"
  TOP_N             - (необязательно) сколько новостей за раз, по умолчанию 10
  TIMEZONE          - (необязательно) часовой пояс, по умолчанию Europe/Kiev
  TZ_OFFSET_HOURS   - (запасной вариант, если TIMEZONE не сработает) напр. 3

Только стандартная библиотека Python (+ tzdata для часового пояса).
"""

import os
import time
import html
import json
import datetime as dt
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# Получатели: одно или несколько ID через запятую.
# Поддерживаются обе переменные — CHAT_IDS (список) и старая CHAT_ID (один).
CHAT_IDS = os.environ.get("CHAT_IDS", "") or os.environ.get("CHAT_ID", "")

# Время рассылки (часы:минуты), через запятую.
SEND_TIMES = os.environ.get("SEND_TIMES", "10:00,15:00,18:00")

# Сколько топ-новостей отправлять за один раз.
TOP_N = int(os.environ.get("TOP_N", "10"))

# Часовой пояс.
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Kiev")
TZ_OFFSET_HOURS = float(os.environ.get("TZ_OFFSET_HOURS", "3"))

# Если "1"/"true"/"yes" — прислать тестовую подборку сразу при запуске.
SEND_ON_START = os.environ.get("SEND_ON_START", "").strip().lower() in ("1", "true", "yes", "on")

# РУССКОЯЗЫЧНЫЕ крипто-новостные RSS-ленты.
FEEDS = [
    "https://ru.cointelegraph.com/rss",   # Cointelegraph на русском
    "https://forklog.com/feed/",          # ForkLog
    "https://bits.media/rss/news/",       # Bits.media
]
# ==================================

USER_AGENT = "Mozilla/5.0 (CryptoNewsBot)"


def get_tz():
    """Часовой пояс: сначала пробуем zoneinfo, иначе фиксированный сдвиг."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE)
    except Exception as e:
        print(f"[warn] не удалось загрузить пояс {TIMEZONE} ({e}), "
              f"использую фиксированный сдвиг UTC+{TZ_OFFSET_HOURS}")
        return dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))


TZ = get_tz()


def parse_send_times():
    """Разбирает SEND_TIMES в список (час, минута)."""
    result = []
    for chunk in SEND_TIMES.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        h, m = chunk.split(":")
        result.append((int(h), int(m)))
    return sorted(result)


def seconds_until_next_run(times):
    """Сколько секунд до ближайшего времени рассылки."""
    now = dt.datetime.now(TZ)
    candidates = []
    for (h, m) in times:
        run = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if run <= now:
            run = run + dt.timedelta(days=1)  # уже прошло сегодня — берём завтра
        candidates.append(run)
    nxt = min(candidates)
    return (nxt - now).total_seconds(), nxt


def fetch_feed(url):
    """Скачивает и парсит одну RSS-ленту, возвращает список (title, link, pub)."""
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


def parse_date(pub):
    """Пытается разобрать дату из RSS для сортировки. Если не вышло — очень старая дата."""
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return dt.datetime.strptime(pub, fmt)
        except Exception:
            continue
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def get_top_news(n):
    """Собирает новости со всех лент, убирает дубли, возвращает n самых свежих."""
    all_items = []
    seen = set()
    for url in FEEDS:
        for title, link, pub in fetch_feed(url):
            if link in seen:
                continue
            seen.add(link)
            all_items.append((title, link, pub))
    # Сортируем по дате, свежие сверху.
    all_items.sort(key=lambda x: parse_date(x[2]), reverse=True)
    return all_items[:n]


def get_recipients():
    """Список ID получателей из CHAT_IDS (через запятую)."""
    return [c.strip() for c in CHAT_IDS.split(",") if c.strip()]


def send_to_chat(chat_id, text):
    """Отправляет сообщение одному получателю."""
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    req = urllib.request.Request(api, data=payload, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        result = json.loads(resp.read().decode())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result


def send_telegram(text):
    """Рассылает сообщение всем получателям. Ошибка одного не ломает остальных."""
    recipients = get_recipients()
    ok_count = 0
    for chat_id in recipients:
        try:
            send_to_chat(chat_id, text)
            ok_count += 1
        except Exception as e:
            print(f"[warn] не удалось отправить получателю {chat_id}: {e}")
    if ok_count == 0 and recipients:
        raise RuntimeError("не удалось отправить ни одному получателю")
    return ok_count


def send_digest():
    """Формирует и отправляет подборку топ-новостей одним сообщением."""
    news = get_top_news(TOP_N)
    if not news:
        print("[info] новостей не найдено, пропускаю рассылку.")
        return
    now_str = dt.datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    lines = [f"📢 <b>Топ крипто-новости</b> — {now_str}\n"]
    for i, (title, link, pub) in enumerate(news, 1):
        title = html.escape(title)
        lines.append(f"{i}. <a href=\"{html.escape(link)}\">{title}</a>")
    message = "\n\n".join(lines)
    # На всякий случай не превышаем лимит Telegram (~4096 символов).
    if len(message) > 4000:
        message = message[:3990] + "…"
    send_telegram(message)
    print(f"[ok] отправлена подборка из {len(news)} новостей.")


def main():
    if not BOT_TOKEN or not get_recipients():
        print("❌ Не заданы BOT_TOKEN и/или CHAT_IDS. На Railway добавь их во вкладке Variables.")
        return

    print(f"[info] получателей: {len(get_recipients())}")
    times = parse_send_times()
    times_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    print(f"✅ Бот запущен. Рассылка топ-{TOP_N} новостей в: {times_str} ({TIMEZONE}).")

    try:
        send_telegram(f"🤖 Бот крипто-новостей запущен.\nБуду присылать топ-{TOP_N} новостей "
                      f"в {times_str} (Киев).")
        print("✅ Тестовое сообщение отправлено.")
    except Exception as e:
        print(f"❌ Не удалось отправить тестовое сообщение. Проверь BOT_TOKEN и CHAT_IDS.\n   {e}")
        return

    # Тестовая подборка сразу при запуске (если включено SEND_ON_START).
    if SEND_ON_START:
        print("[info] SEND_ON_START включён — отправляю тестовую подборку сейчас.")
        try:
            send_digest()
        except Exception as e:
            print(f"[error] сбой при тестовой рассылке: {e}")

    while True:
        wait, nxt = seconds_until_next_run(times)
        print(f"[info] следующая рассылка: {nxt.strftime('%d.%m %H:%M')} "
              f"(через {int(wait // 60)} мин).")
        # Спим кусками, чтобы процесс не «зависал» надолго.
        while wait > 0:
            chunk = min(wait, 300)
            time.sleep(chunk)
            wait -= chunk
        try:
            send_digest()
        except Exception as e:
            print(f"[error] сбой при рассылке: {e}")
        # Небольшая пауза, чтобы не сработать дважды на одну минуту.
        time.sleep(60)


if __name__ == "__main__":
    main()
