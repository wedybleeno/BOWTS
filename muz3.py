#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
import uuid
import asyncio
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from yt_dlp import YoutubeDL

from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# ================== НАСТРОЙКИ ==================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения или .env")
CHANNEL_ID = os.getenv("FORWARD_CHANNEL_ID", "-1003056741244").strip()                # "-100xxxxxxxxxxxx" или пусто, чтобы не дублировать
OWNER_USER_ID = int(os.getenv("OWNER_USER_ID", "0")) or None            # опционально (дублирование в ЛС владельцу из канала)
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
ARCHIVE_FILE = os.getenv("URL_ARCHIVE_FILE", "sent_urls.txt")           # сюда пишем УСПЕШНО отправленные URL (без дублей)
MP3_QUALITY = os.getenv("MP3_QUALITY", "128")                            # 128/192/320
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "2"))                         # пул потоков для yt-dlp

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ================== ЛОГИ ==================
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("queue-bot")

# ================== РЕГЕКСПЫ ==================
URL_ANY_RE = re.compile(r'https?://\S+', re.I)
URL_YT_SC_RE = re.compile(
    r'https?://(?:'
    r'(?:www\.)?youtube\.com/|youtu\.be/|'
    r'soundcloud\.com|snd\.sc'
    r')\S*',
    re.I
)

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', (filename or "").strip()) or "audio"

def extract_all_urls(text: str) -> list[str]:
    return [m.group(0) for m in URL_ANY_RE.finditer(text or "")]

# ================== АРХИВ (чтобы уметь продолжать и не дублировать) ==================
def load_archive() -> set[str]:
    if not os.path.exists(ARCHIVE_FILE):
        return set()
    with open(ARCHIVE_FILE, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

def append_archive(url: str):
    with open(ARCHIVE_FILE, "a", encoding="utf-8") as f:
        f.write(url.strip() + "\n")

SENT_ARCHIVE = load_archive()

# ================== ПУЛ ДЛЯ yt-dlp ==================
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

# ================== СКАЧИВАНИЕ ==================
def download_track(url: str):
    """
    Скачивает аудио (YouTube/SoundCloud) и конвертит в MP3 (MP3_QUALITY).
    Возвращает (путь_к_mp3, title) или (None, None).
    """
    unique_filename = str(uuid.uuid4())
    temp_path = os.path.join(DOWNLOAD_DIR, unique_filename)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_path,
        'noplaylist': True,
        'quiet': False,            # делаем «болтливым» для отладки
        'no_warnings': False,

        # Устойчивость
        'retries': 5,
        'fragment_retries': 5,
        'socket_timeout': 25,
        'geo_bypass': True,
        'nocheckcertificate': True,

        # Для YouTube
        'extract_flat': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web']
            }
        },
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,

        # Конвертация в MP3
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': MP3_QUALITY,
        }],
    }

    logger.info(f"⏬ Скачиваю: {url}")
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                logger.error("yt_dlp вернул None для url=%s", url)
                return None, None
            if isinstance(info, dict) and info.get('entries'):
                info = info['entries'][0]
            title = sanitize_filename(info.get('title') or 'Unknown')
        final_file = f"{temp_path}.mp3"
        if not os.path.exists(final_file):
            logger.warning("Файл не найден после конвертации: %s", final_file)
            return None, None
        logger.info(f"📦 Готов файл: {final_file}")
        return final_file, title
    except Exception as e:
        logger.error("Ошибка при скачивании (%s): %s", url, e)
        return None, None

# ================== ОТПРАВКА (ЛС + опционально канал) ==================
async def send_audio_dual(
    context: ContextTypes.DEFAULT_TYPE,
    primary_chat_id: int | str,
    secondary_chat_id: int | str | None,
    file_path: str,
    title: str,
    caption_for_channel: str | None = None,
    to_channel_first: bool = False,
):
    async def _send_file(chat_id):
        with open(file_path, 'rb') as f:
            return await context.bot.send_audio(
                chat_id=chat_id,
                audio=InputFile(f, filename=f"{title}.mp3"),
                title=title,
                caption=(caption_for_channel if (str(chat_id) == str(CHANNEL_ID) and caption_for_channel) else None)
            )

    if secondary_chat_id is None:
        return await _send_file(primary_chat_id)

    first_id, second_id = (CHANNEL_ID, secondary_chat_id) if to_channel_first else (primary_chat_id, secondary_chat_id)

    # 1) первая отправка
    msg = await _send_file(first_id)
    file_id = msg.audio.file_id if msg and msg.audio else None

    # 2) второе место по file_id
    try:
        if file_id:
            await context.bot.send_audio(
                chat_id=second_id,
                audio=file_id,
                title=title,
                caption=(caption_for_channel if (str(second_id) == str(CHANNEL_ID) and caption_for_channel) else None)
            )
        else:
            await _send_file(second_id)
    except Exception as e:
        logger.error("Вторая отправка не удалась: %s", e)

    return msg

# ================== ОЧЕРЕДИ ==================
CHAT_QUEUES: dict[int, asyncio.Queue] = {}
CHAT_WORKING: set[int] = set()
CHAT_SENT_COUNT: dict[int, int] = {}  # сколько отправлено за текущий запуск

def enqueue_urls_for_chat(chat_id: int, urls: list[str]):
    """Фильтруем уже обработанные (по архиву), кладём остальное в очередь этого чата."""
    fresh = []
    for u in urls:
        u = u.strip()
        if not u:
            continue
        if u in SENT_ARCHIVE:
            # уже отправляли — пропускаем
            continue
        fresh.append(u)

    q = CHAT_QUEUES.setdefault(chat_id, asyncio.Queue())
    for u in fresh:
        q.put_nowait(u)
    return q.qsize(), len(fresh), len(urls) - len(fresh)

async def ensure_worker(context_chat_update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    """Запуск воркера для чата (если ещё не запущен). Воркера всегда один — обрабатывает по очереди."""
    if chat_id in CHAT_WORKING:
        return
    CHAT_WORKING.add(chat_id)
    CHAT_SENT_COUNT.setdefault(chat_id, 0)

    queue = CHAT_QUEUES.setdefault(chat_id, asyncio.Queue())
    await context_chat_update.effective_chat.send_message(
        f"✅ Запустил обработчик. В очереди сейчас: {queue.qsize()} ссылок."
    )

    try:
        while True:
            url = await queue.get()
            try:
                # Скачивание (в пуле)
                loop = asyncio.get_event_loop()
                file_path, title = await loop.run_in_executor(executor, partial(download_track, url))

                if not file_path or not os.path.exists(file_path):
                    await context.bot.send_message(chat_id=chat_id, text=f"❌ Не удалось скачать: {url}")
                    continue

                # Отправка: тебе -> (опц.) в канал
                await send_audio_dual(
                    context=context,
                    primary_chat_id=chat_id,
                    secondary_chat_id=int(CHANNEL_ID) if str(CHANNEL_ID).lstrip("-").isdigit() else (CHANNEL_ID or None),
                    file_path=file_path,
                    title=title,
                    caption_for_channel=f"🎵 {title}",
                    to_channel_first=False
                )

                # Отмечаем в архиве ТОЛЬКО после удачной отправки
                append_archive(url)
                SENT_ARCHIVE.add(url)
                CHAT_SENT_COUNT[chat_id] += 1

                # Чистим локальный файл
                try:
                    os.remove(file_path)
                except Exception as e:
                    logger.error("Ошибка удаления файла %s: %s", file_path, e)

                logger.info(f"✅ Отправлено: {title}")

            except Exception as e:
                logger.error("Ошибка обработки URL %s: %s", url, e)
            finally:
                queue.task_done()

    except asyncio.CancelledError:
        pass
    finally:
        CHAT_WORKING.discard(chat_id)

# ================== ХЭНДЛЕРЫ ==================
async def cmd_start(update: Update, _: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Кинь ссылки YouTube/SoundCloud — можно огромным списком (по строке или через пробелы).\n"
        "Бот поставит их в очередь и будет по одной: скачать → отправить → (опц.) в канал → удалить.\n"
        "Уже отправленные ссылки сохраняются в sent_urls.txt — повтора не будет.\n\n"
        "Можно прислать .txt с ссылками (как документ). Команда: /status — показать прогресс."
    )

async def cmd_status(update: Update, _: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = CHAT_QUEUES.get(chat_id)
    qs = q.qsize() if q else 0
    sent = CHAT_SENT_COUNT.get(chat_id, 0)
    await update.message.reply_text(
        f"📊 Очередь: {qs} ссылок.\n"
        f"Отправлено за этот запуск: {sent}\n"
        f"Всего в архиве: {len(SENT_ARCHIVE)}"
    )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    urls_all = extract_all_urls(text)
    urls = [u for u in urls_all if URL_YT_SC_RE.search(u)]

    if not urls:
        await update.message.reply_text("Дай ссылки YouTube/SoundCloud. Можно много сразу.")
        return

    queued_total, added_now, skipped_dupes = enqueue_urls_for_chat(update.effective_chat.id, urls)
    await update.message.reply_text(
        f"Добавил {added_now} новых ссылок (пропущено как уже отправленные: {skipped_dupes}). "
        f"В очереди сейчас: {queued_total}"
    )
    await ensure_worker(update, context, update.effective_chat.id)

async def handle_textfile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Принимаем .txt с ссылками (как документ), парсим, добавляем в очередь."""
    doc = update.message.document
    if not doc or doc.mime_type not in ("text/plain",):
        await update.message.reply_text("Пришли .txt (text/plain) с ссылками.")
        return

    tmp = os.path.join(DOWNLOAD_DIR, f"links_{uuid.uuid4().hex}.txt")
    tg_file = await context.bot.get_file(doc.file_id)
    await tg_file.download_to_drive(tmp)

    try:
        with open(tmp, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        urls_all = extract_all_urls(content)
        urls = [u for u in urls_all if URL_YT_SC_RE.search(u)]
        if not urls:
            await update.message.reply_text("В файле не нашёл валидных YouTube/SoundCloud ссылок.")
            return

        queued_total, added_now, skipped_dupes = enqueue_urls_for_chat(update.effective_chat.id, urls)
        await update.message.reply_text(
            f"Из файла добавил {added_now} новых ссылок (пропущено как уже отправленные: {skipped_dupes}). "
            f"В очереди: {queued_total}"
        )
        await ensure_worker(update, context, update.effective_chat.id)
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

# ================== MAIN ==================
def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler('start', cmd_start))
    application.add_handler(CommandHandler('status', cmd_status))

    # ЛС: текстовые сообщения со ссылками
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    # ЛС: .txt документы со ссылками
    application.add_handler(
        MessageHandler(filters.ChatType.PRIVATE & filters.Document.MimeType("text/plain"), handle_textfile)
    )

    application.run_polling(allowed_updates=["message"])

    # финальная уборка tmp
    try:
        for fn in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, fn)
            if os.path.isfile(path):
                os.remove(path)
    except Exception as e:
        logger.error("Ошибка при удалении временных файлов: %s", e)

if __name__ == '__main__':
    main()
