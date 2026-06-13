#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import uuid
import asyncio
import shutil
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from yt_dlp import YoutubeDL
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# -------------------- НАСТРОЙКИ --------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения или .env")
CHANNEL_ID = os.getenv("FORWARD_CHANNEL_ID", "-1003056741244").strip()        # "-100xxxxxxxxxxxx" или пусто
COOKIES_PATH = os.getenv("SC_COOKIES_TXT", "").strip()          # cookies.txt (если лайки приватные)
OUTDIR = os.getenv("OUTDIR", "sc_downloads")
ARCHIVE = os.getenv("SC_ARCHIVE", "downloaded_soundcloud.txt")  # архив УСПЕШНО отправленных (см. ниже)
MP3_KBPS = int(os.getenv("SC_MP3_KBPS", "192"))                 # 128/192/320
MIN_SLEEP = float(os.getenv("SC_MIN_SLEEP", "0.6"))
MAX_SLEEP = float(os.getenv("SC_MAX_SLEEP", "1.2"))

# Сколько раз пробовать ПЕРЕкачать и ПЕРЕотправить, если отправка не удалась
MAX_SEND_RETRIES = int(os.getenv("SC_MAX_SEND_RETRIES", "3"))

os.makedirs(OUTDIR, exist_ok=True)

# Блокирующие операции — в пул
executor = ThreadPoolExecutor(max_workers=2)

LIKES_RE = re.compile(r'^https?://soundcloud\.com/[^/]+/likes/?$', re.I)

def safe_name(s: str) -> str:
    import re as _re
    return _re.sub(r'[<>:"/\\|?*\n\r\t]+', '_', (s or "").strip()) or "audio"

# -------------------- yt-dlp ОПЦИИ --------------------
def build_ydl_opts(use_archive: bool = True):
    """
    use_archive=True — отмечаем треки как скачанные ТОЛЬКО когда отправка успешно завершилась.
    Для этого архив подключаем ТОЛЬКО в «финальном» проходе (после успешной отправки).
    На этапе ретраев use_archive=False, чтобы принудительно перекачать.
    """
    outtmpl = os.path.join(OUTDIR, "%(id)s.%(ext)s")
    postprocessors = [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": str(MP3_KBPS)
    }]
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "nocheckcertificate": True,
        "geo_bypass": True,
        "ignoreerrors": False,   # пусть кидает исключения — мы обработаем
        "outtmpl": outtmpl,
        "format": "bestaudio/best",
        "postprocessors": postprocessors,
        "merge_output_format": "mp3",
        "retries": 5,
        "fragment_retries": 5,
        "socket_timeout": 25,
        "sleep_interval_requests": MIN_SLEEP,
        "max_sleep_interval_requests": MAX_SLEEP,
        # архив подключаем опционально (см. выше)
    }
    if use_archive:
        opts["download_archive"] = ARCHIVE
    if COOKIES_PATH and os.path.exists(COOKIES_PATH):
        opts["cookies"] = COOKIES_PATH
    return opts

# -------------------- ВСПОМОГАТЕЛЬНЫЕ --------------------
def _extract_playlist(url: str, use_archive: bool = False):
    with YoutubeDL(build_ydl_opts(use_archive=use_archive)) as ydl:
        return ydl.extract_info(url, download=False)

def _download_one(entry_url: str, use_archive: bool = False):
    """
    Скачивает ОДИН трек -> mp3. Возвращает (path_mp3, artist, title, track_id).
    use_archive=False для ретраев (иначе ydl пропустит).
    """
    with YoutubeDL(build_ydl_opts(use_archive=use_archive)) as ydl:
        info = ydl.extract_info(entry_url, download=False)
        if not info:
            return None, None, None, None
        if "entries" in info and info["entries"]:
            info = info["entries"][0]

        track_id = info.get("id")
        artist = safe_name(info.get("uploader") or info.get("uploader_id") or info.get("artist") or "")
        title = safe_name(info.get("title") or "audio")

        print(f"⏬ Скачиваю: {artist} - {title}")
        ydl.download([entry_url])

        # ожидаемый файл
        if track_id:
            cand = os.path.join(OUTDIR, f"{track_id}.mp3")
            if os.path.exists(cand) and os.path.getsize(cand) > 0:
                return cand, artist, title, track_id

        # запасной поиск
        for fn in os.listdir(OUTDIR):
            if fn.lower().endswith(".mp3") and (track_id and track_id in fn):
                path = os.path.join(OUTDIR, fn)
                if os.path.getsize(path) > 0:
                    return path, artist, title, track_id

        return None, artist, title, track_id

async def _send_to_user_and_channel(context: ContextTypes.DEFAULT_TYPE, chat_id: int | str,
                                    path_mp3: str, title_for_user: str) -> None:
    """
    Отправляет СНАЧАЛА пользователю, затем (если задан CHANNEL_ID) в канал по file_id.
    Если любой этап падает — бросает исключение (чтобы запустился ретрай).
    """
    # Пользователь:
    try:
        with open(path_mp3, "rb") as f:
            msg = await context.bot.send_audio(
                chat_id=chat_id,
                audio=InputFile(f, filename=f"{title_for_user}.mp3"),
                title=title_for_user,
                caption=f"🎵 {title_for_user}"
            )
        file_id = msg.audio.file_id if (msg and msg.audio) else None
    except Exception as e:
        raise RuntimeError(f"Не удалось отправить пользователю: {e}")

    # Канал (если нужен):
    if CHANNEL_ID:
        try:
            if file_id:
                await context.bot.send_audio(
                    chat_id=CHANNEL_ID,
                    audio=file_id,
                    title=title_for_user,
                    caption=f"🎵 {title_for_user}"
                )
            else:
                with open(path_mp3, "rb") as f:
                    await context.bot.send_audio(
                        chat_id=CHANNEL_ID,
                        audio=InputFile(f, filename=f"{title_for_user}.mp3"),
                        title=title_for_user,
                        caption=f"🎵 {title_for_user}"
                    )
        except Exception as e:
            raise RuntimeError(f"Не удалось отправить в канал: {e}")

async def _process_one_entry(context: ContextTypes.DEFAULT_TYPE, chat_id: int | str, entry_url: str) -> bool:
    """
    Полный цикл ДЛЯ ОДНОГО ТРЕКА:
    [скачать] -> [отправить юзеру] -> [отправить в канал] -> [удалить локально]
    Если отправка не удалась: удалить файл, ПЕРЕКАЧАТЬ и попробовать снова (до MAX_SEND_RETRIES).
    Возвращает True при полном успехе (и только тогда трек попадёт в архив), иначе False.
    """
    loop = asyncio.get_event_loop()

    for attempt in range(1, MAX_SEND_RETRIES + 1):
        path_mp3 = None
        try:
            # На ретраях НЕ используем архив, чтобы принудительно перекачать
            path_mp3, artist, title, track_id = await loop.run_in_executor(
                executor, partial(_download_one, entry_url, False if attempt > 1 else False)
            )
            if not path_mp3 or not os.path.exists(path_mp3) or os.path.getsize(path_mp3) == 0:
                print(f"❌ Не скачалось (попытка {attempt}/{MAX_SEND_RETRIES}).")
                continue

            nice_title = safe_name(f"{artist} - {title}") if artist else safe_name(title)
            # Отправка
            await _send_to_user_and_channel(context, chat_id, path_mp3, nice_title)
            print(f"✅ Отправлен: {nice_title}")

            # Удаляем локальный файл
            try:
                os.remove(path_mp3)
            except Exception:
                pass

            # Помечаем в download_archive ТОЛЬКО после полной удачной отправки
            # Для этого сделаем «пустую» загрузку c use_archive=True: yt-dlp сам добавит ID,
            # но скачивания не будет, т.к. файл уже удалён и он не нужен.
            try:
                await loop.run_in_executor(executor, partial(_extract_playlist, entry_url, True))
            except Exception:
                pass

            return True

        except Exception as e:
            print(f"🚨 Ошибка отправки (попытка {attempt}/{MAX_SEND_RETRIES}): {e}")
        finally:
            # На провале отправки — удаляем файл, чтобы не зависала старая версия
            try:
                if path_mp3 and os.path.exists(path_mp3):
                    os.remove(path_mp3)
            except Exception:
                pass

    print("⛔ Не удалось после всех попыток.")
    return False

# -------------------- ОСНОВНОЙ ПРОЦЕСС --------------------
async def process_likes_sequential(context: ContextTypes.DEFAULT_TYPE, chat_id: int, likes_url: str):
    """
    Получаем список лайков и ИДЁМ СТРОГО ПО ПОРЯДКУ:
    для каждого трека — скачать → отправить → удалить; при фейле отправки — перекачать и ретраить.
    """
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(executor, partial(_extract_playlist, likes_url, False))
    except Exception as e:
        await context.bot.send_message(chat_id=chat_id, text=f"❌ Не удалось получить список лайков: {e}")
        return

    entries = [e for e in (info.get("entries") or []) if e]
    total = len(entries)
    if total == 0:
        await context.bot.send_message(chat_id=chat_id, text="Похоже, в лайках пусто или недоступно.")
        return

    await context.bot.send_message(chat_id=chat_id, text=f"🚀 Нашёл ~{total} трек(ов). Начинаю по очереди…")

    sent = 0
    failed = 0

    for idx, entry in enumerate(entries, 1):
        entry_url = entry.get("webpage_url") or entry.get("url")
        if not entry_url:
            print(f"⏭ Пропуск {idx}/{total} — нет URL")
            failed += 1
            continue

        print(f"\n—— [{idx}/{total}] — {entry_url}")
        ok = await _process_one_entry(context, chat_id, entry_url)
        if ok:
            sent += 1
        else:
            failed += 1

    await context.bot.send_message(chat_id=chat_id, text=f"🎉 Готово. Отправлено: {sent}. Ошибок: {failed}.")

# -------------------- ТЕЛЕГРАМ --------------------
async def start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Кинь ссылку на лайки SoundCloud — я пошлю ВСЕ треки по очереди сюда и (если задан) в канал.\n\n"
        "Пример:\nhttps://soundcloud.com/<username>/likes\n\n"
        "Лог работы видно в консоли: скачал → отправил → удалил, с ретраями."
    )

async def handle_private_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not LIKES_RE.match(text):
        await update.message.reply_text("Дай ссылку вида:\nhttps://soundcloud.com/<username>/likes")
        return

    await update.message.reply_text("Окей! Поехали по лайкам по очереди… Логи смотри в консоли.")
    # Ведём строго последовательно (без фона), чтобы всё было в одном порядке
    await process_likes_sequential(context, update.effective_chat.id, text)

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_private_text))
    app.run_polling(allowed_updates=["message"])

    # уборка пустой папки
    try:
        if os.path.isdir(OUTDIR) and not os.listdir(OUTDIR):
            shutil.rmtree(OUTDIR, ignore_errors=True)
    except Exception:
        pass

if __name__ == "__main__":
    main()
