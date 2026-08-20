#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Крипто-новости -> Telegram bot
Присылает топ-новости на русском отдельными постами (картинка + краткое
описание + ссылка «Читать»), как в новостных Telegram-каналах.
По умолчанию 3 раза в день: 10:00, 15:00, 18:00 по киевскому времени.

Переменные окружения (Railway -> Variables):
  BOT_TOKEN         - токен бота от @BotFather
  CHAT_IDS          - ID получателей через запятую (или старая CHAT_ID)
  SEND_TIMES        - (необязательно) время рассылки, напр. "10:00,15:00,18:00"
  TOP_N             - (необязательно) сколько новостей за раз, по умолчанию 10
  TIMEZONE          - (необязательно) часовой пояс, по умолчанию Europe/Kiev
  TZ_OFFSET_HOURS   - (запасной сдвиг, если TIMEZONE не сработает) напр. 3
  SEND_ON_START     - "1" чтобы прислать тестовую подборку сразу при запуске

Только стандартная библиотека Python (+ tzdata для часового пояса).
"""

import os
import re
import time
import html
import json
import datetime as dt
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

# ============ НАСТРОЙКИ ============
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_IDS = os.environ.get("CHAT_IDS", "") or os.environ.get("CHAT_ID", "")
SEND_TIMES = os.environ.get("SEND_TIMES", "10:00,15:00,18:00")
TOP_N = int(os.environ.get("TOP_N", "10"))
TIMEZONE = os.environ.get("TIMEZONE", "Europe/Kiev")
TZ_OFFSET_HOURS = float(os.environ.get("TZ_OFFSET_HOURS", "3"))
SEND_ON_START = os.environ.get("SEND_ON_START", "").strip().lower() in ("1", "true", "yes", "on")

# РУССКОЯЗЫЧНЫЕ крипто-новостные RSS-ленты.
FEEDS = [
    "https://ru.cointelegraph.com/rss",   # Cointelegraph на русском
    "https://forklog.com/feed/",          # ForkLog
    "https://bits.media/rss/news/",       # Bits.media
]
# ==================================

USER_AGENT = "Mozilla/5.0 (CryptoNewsBot)"
CAPTION_LIMIT = 1000   # запас под лимит подписи Telegram (1024)
DESC_LIMIT = 350       # сколько символов описания оставлять


def get_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(TIMEZONE)
    except Exception as e:
        print(f"[warn] не удалось загрузить пояс {TIMEZONE} ({e}), "
              f"использую фиксированный сдвиг UTC+{TZ_OFFSET_HOURS}")
        return dt.timezone(dt.timedelta(hours=TZ_OFFSET_HOURS))


TZ = get_tz()


def get_recipients():
    return [c.strip() for c in CHAT_IDS.split(",") if c.strip()]


def parse_send_times():
    result = []
    for chunk in SEND_TIMES.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        h, m = chunk.split(":")
        result.append((int(h), int(m)))
    return sorted(result)


def seconds_until_next_run(times):
    now = dt.datetime.now(TZ)
    candidates = []
    for (h, m) in times:
        run = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if run <= now:
            run = run + dt.timedelta(days=1)
        candidates.append(run)
    nxt = min(candidates)
    return (nxt - now).total_seconds(), nxt


def local_tag(tag):
    """Имя тега без namespace, напр. '{...}content' -> 'content'."""
    return tag.rsplit("}", 1)[-1].lower()


def strip_html(text):
    """Убирает HTML-теги и лишние пробелы из описания."""
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_image(item):
    """Пытается найти картинку новости в разных форматах RSS."""
    # 1) enclosure / media:content / media:thumbnail с url
    for el in item.iter():
        name = local_tag(el.tag)
        if name in ("enclosure", "content", "thumbnail"):
            url = el.attrib.get("url", "")
            typ = el.attrib.get("type", "")
            if url and (typ.startswith("image") or re.search(r"\.(jpg|jpeg|png|webp)", url, re.I)):
                return url
    # 2) первая <img> внутри description / content:encoded
    for el in item.iter():
        if local_tag(el.tag) in ("description", "encoded"):
            m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', el.text or "", re.I)
            if m:
                return m.group(1)
    return None


def parse_date(pub):
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return dt.datetime.strptime(pub, fmt)
        except Exception:
            continue
    return dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


def fetch_feed(url):
    """Возвращает список словарей: title, link, pub, desc, image."""
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            desc = strip_html(item.findtext("description") or "")
            image = extract_image(item)
            if title and link:
                items.append({
                    "title": title, "link": link, "pub": pub,
                    "desc": desc, "image": image,
                })
    except Exception as e:
        print(f"[warn] не удалось прочитать ленту {url}: {e}")
    return items


def get_top_news(n):
    all_items = []
    seen = set()
    for url in FEEDS:
        for it in fetch_feed(url):
            if it["link"] in seen:
                continue
            seen.add(it["link"])
            all_items.append(it)
    all_items.sort(key=lambda x: parse_date(x["pub"]), reverse=True)
    return all_items[:n]


def build_caption(it):
    """Формирует подпись поста: заголовок + краткое описание + ссылка."""
    title = html.escape(it["title"])
    link = html.escape(it["link"])
    desc = it["desc"]
    if len(desc) > DESC_LIMIT:
        desc = desc[:DESC_LIMIT].rsplit(" ", 1)[0] + "…"
    desc = html.escape(desc)

    parts = [f"📰 <b>{title}</b>"]
    if desc:
        parts.append(desc)
    parts.append(f'<a href="{link}">➡️ Читать полностью</a>')
    caption = "\n\n".join(parts)
    if len(caption) > CAPTION_LIMIT:
        caption = caption[:CAPTION_LIMIT - 1] + "…"
    return caption


def tg_request(method, params):
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(api, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def send_post(chat_id, it):
    """Отправляет одну новость: фото с подписью, либо текст со ссылкой."""
    caption = build_caption(it)
    if it["image"]:
        res = tg_request("sendPhoto", {
            "chat_id": chat_id,
            "photo": it["image"],
            "caption": caption,
            "parse_mode": "HTML",
        })
        if res.get("ok"):
            return True
        # Если картинка «не понравилась» Telegram — шлём текстом с превью.
        print(f"[warn] фото не отправилось ({res.get('description')}), шлю текстом.")
    res = tg_request("sendMessage", {
        "chat_id": chat_id,
        "text": caption,
        "parse_mode": "HTML",
        "disable_web_page_preview": "false",  # пусть Telegram сам подтянет превью
    })
    return bool(res.get("ok"))


def send_text_all(text):
    """Простое текстовое сообщение всем получателям (для служебных уведомлений)."""
    for chat_id in get_recipients():
        try:
            tg_request("sendMessage", {
                "chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": "true",
            })
        except Exception as e:
            print(f"[warn] не удалось уведомить {chat_id}: {e}")


def send_digest():
    """Рассылает топ-новости отдельными постами всем получателям."""
    news = get_top_news(TOP_N)
    if not news:
        print("[info] новостей не найдено, пропускаю рассылку.")
        return
    recipients = get_recipients()
    now_str = dt.datetime.now(TZ).strftime("%d.%m.%Y %H:%M")
    # Заголовок подборки.
    send_text_all(f"🗞 <b>Крипто-новости</b> — {now_str}")
    sent = 0
    for it in news:
        for chat_id in recipients:
            try:
                if send_post(chat_id, it):
                    sent += 1
            except Exception as e:
                print(f"[warn] пост не ушёл получателю {chat_id}: {e}")
        time.sleep(1)  # пауза, чтобы не упереться в лимиты Telegram
    print(f"[ok] разослано {len(news)} новостей ({sent} доставок).")


def main():
    if not BOT_TOKEN or not get_recipients():
        print("❌ Не заданы BOT_TOKEN и/или CHAT_IDS. На Railway добавь их во вкладке Variables.")
        return

    times = parse_send_times()
    times_str = ", ".join(f"{h:02d}:{m:02d}" for h, m in times)
    print(f"✅ Бот запущен. Получателей: {len(get_recipients())}. "
          f"Рассылка топ-{TOP_N} новостей в: {times_str} ({TIMEZONE}).")

    try:
        send_text_all(f"🤖 Бот крипто-новостей запущен.\nТоп-{TOP_N} новостей "
                      f"в {times_str} (Киев), отдельными постами с картинками.")
        print("✅ Стартовое сообщение отправлено.")
    except Exception as e:
        print(f"❌ Не удалось отправить стартовое сообщение. Проверь BOT_TOKEN и CHAT_IDS.\n   {e}")
        return

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
        while wait > 0:
            chunk = min(wait, 300)
            time.sleep(chunk)
            wait -= chunk
        try:
            send_digest()
        except Exception as e:
            print(f"[error] сбой при рассылке: {e}")
        time.sleep(60)


if __name__ == "__main__":
    main()
