#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import uuid
import asyncio
import logging
import shutil
import subprocess
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# ================== НАСТРОЙКИ ==================
# Положи токен в переменную окружения TELEGRAM_TOKEN
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения или .env")

# Если хочешь дублировать в канал — укажи ID канала, например "-1003056741244".
CHANNEL_ID = os.getenv("FORWARD_CHANNEL_ID", "").strip()  # пусто = не дублируем

# Можно указать свой user_id, если захочешь когда-нибудь дублировать в ЛС владельцу.
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0")) or None

WORKDIR = "downloads"
os.makedirs(WORKDIR, exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("yt-mp3-bot")

# Параллелим тяжёлые I/O штуки
executor = ThreadPoolExecutor(max_workers=4)

# ================== ПАРСИНГ СООБЩЕНИЙ ==================
URL_RE = re.compile(r'https?://\S+', re.I)
TIME_RANGE_RE = re.compile(r'(?P<s>\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(?P<e>\d{1,2}:\d{2}(?::\d{2})?)')

def norm_time(t: str) -> str:
    """
    0:15 -> 00:00:15
    1:02 -> 00:01:02
    01:02:03 -> 01:02:03
    """
    parts = t.split(':')
    if len(parts) == 2:
        mm, ss = parts
        return f"00:{int(mm):02d}:{int(ss):02d}"
    if len(parts) == 3:
        hh, mm, ss = parts
        return f"{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    raise ValueError("Bad time format")

def parse_message(text: str):
    """
    Возвращает (url, start, end)
    url — обязателен; start/end — могут быть None (тогда вытащим весь трек)
    """
    url_m = URL_RE.search(text or "")
    url = url_m.group(0) if url_m else None

    start = end = None
    tr = TIME_RANGE_RE.search(text or "")
    if tr:
        start = norm_time(tr.group('s'))
        end   = norm_time(tr.group('e'))

    return url, start, end

def safe_name(s: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\n\r\t]+', '_', s).strip()
    return s or "audio"

# ================== СКАЧИВАНИЕ ВИДЕО ==================
def download_video(url: str):
    """
    Скачивает лучшее доступное видео+аудио, мёрджит в mp4 (если возможно).
    Возвращает (final_video_path, title).
    """
    uid = str(uuid.uuid4())
    outtmpl = os.path.join(WORKDIR, uid)

    ydl_opts = {
        "format": "bv*+ba/b",                   # лучшая пара
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "retries": 3,
        "fragment_retries": 3,
        "socket_timeout": 15,
        "geo_bypass": True,
        "nocheckcertificate": True,
        "merge_output_format": "mp4",
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}
        ],
        "extractor_args": {
            "youtube": {"player_client": ["android", "web"]},
        },
        "youtube_include_dash_manifest": False,
        "youtube_include_hls_manifest": False,
    }

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if isinstance(info, dict) and info.get("entries"):
            info = info["entries"][0]
        title = safe_name(info.get("title") or "audio")
        # yt-dlp после ремакса обычно положит .mp4
        for ext in (".mp4", ".mkv", ".webm", ".mov"):
            cand = outtmpl + ext
            if os.path.exists(cand):
                return cand, title
        if os.path.exists(outtmpl):
            return outtmpl, title
    return None, None

# ================== ВЫРЕЗКА В MP3 ==================
def cut_audio(src: str, start: str | None, end: str | None, title_hint: str = "audio") -> str:
    """
    Вырезает нужный фрагмент из видео и конвертирует в MP3 (libmp3lame).
    Возвращает путь к готовому mp3.
    """
    uid = str(uuid.uuid4())
    # Имя файла оставим техническим, в отправке укажем красивое имя через filename/title
    dst = os.path.join(WORKDIR, f"{uid}.mp3")

    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", start]
    if end:
        cmd += ["-to", end]
    cmd += ["-i", src]
    cmd += [
        "-vn",                  # без видео
        "-acodec", "libmp3lame",
        "-ar", "44100",
        "-b:a", "192k",
        "-movflags", "+faststart",
        dst
    ]

    log.info("FFmpeg: %s", " ".join(cmd))
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        raise RuntimeError("FFmpeg не создал выходной mp3")
    return dst

# ================== ОТПРАВКА АУДИО ==================
async def send_audio(context: ContextTypes.DEFAULT_TYPE,
                     primary_chat_id: int | str,
                     file_path: str,
                     title: str,
                     caption: str = "",
                     duplicate_to_channel: bool = False):
    # 1) инициатору
    with open(file_path, "rb") as f:
        msg = await context.bot.send_audio(
            chat_id=primary_chat_id,
            audio=InputFile(f, filename=f"{title}.mp3"),
            title=title,
            caption=caption
        )
    file_id = msg.audio.file_id if (msg and msg.audio) else None

    # 2) опционально — дублируем в канал
    if duplicate_to_channel and CHANNEL_ID:
        try:
            if file_id:
                await context.bot.send_audio(chat_id=CHANNEL_ID, audio=file_id, title=title, caption=caption)
            else:
                with open(file_path, "rb") as f:
                    await context.bot.send_audio(chat_id=CHANNEL_ID, audio=InputFile(f), title=title, caption=caption)
        except Exception as e:
            log.error("Не удалось продублировать в канал: %s", e)

# ================== ХЭНДЛЕРЫ ==================
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Кинь ссылку на YouTube и диапазон времени.\n\n"
        "Примеры:\n"
        "1) Полностью в mp3:  https://youtu.be/xxxx\n"
        "2) Отрезок в mp3:    https://youtu.be/xxxx 00:30-01:20\n"
        "Форматы времени: mm:ss или hh:mm:ss (оба края включительно)."
    )

async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    url, start, end = parse_message(text)

    if not url:
        await update.message.reply_text("Дай ссылку на YouTube. Можно добавить диапазон `00:00-01:55`.")
        return

    loop = asyncio.get_event_loop()

    # 1) Скачиваем видео
    src_path, title = await loop.run_in_executor(executor, partial(download_video, url))
    if not src_path or not os.path.exists(src_path):
        await update.message.reply_text("Не удалось скачать видео. Попробуй другую ссылку.")
        return

    out_path = None
    try:
        # 2) Если указан диапазон — режем, иначе вытаскиваем весь трек
        out_path = await loop.run_in_executor(executor, partial(cut_audio, src_path, start, end, title))
        # 3) Отправляем как аудио
        await send_audio(
            context=context,
            primary_chat_id=update.effective_chat.id,
            file_path=out_path,
            title=title,
            caption=f"🎵 {title}",
            duplicate_to_channel=bool(CHANNEL_ID)
        )
    except Exception as e:
        log.error("Ошибка обработки: %s", e)
        await update.message.reply_text("Ошибка при обработке. Проверь время/ссылку и попробуй ещё раз.")
    finally:
        # чистим временные файлы
        for fp in (out_path, src_path):
            try:
                if fp and os.path.exists(fp):
                    os.remove(fp)
            except Exception:
                pass
        # зачистка .part, если остались
        try:
            for fn in os.listdir(WORKDIR):
                if fn.endswith(".part"):
                    os.remove(os.path.join(WORKDIR, fn))
        except Exception:
            pass

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_private_text))
    app.run_polling(allowed_updates=["message"])

    # уборка пустой папки
    try:
        if os.path.isdir(WORKDIR) and not os.listdir(WORKDIR):
            shutil.rmtree(WORKDIR, ignore_errors=True)
    except Exception:
        pass

if __name__ == "__main__":
    main()
