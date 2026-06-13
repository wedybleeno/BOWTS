#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import re
import uuid
import asyncio
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from yt_dlp import YoutubeDL

from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# ================== НАСТРОЙКИ ==================
# Можно задать токен и через переменную окружения TELEGRAM_TOKEN
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения или .env")

# ID канала: лучше числовой вида -100xxxxxxxxxx. Можно @username, но числовой надёжнее.
CHANNEL_ID = os.getenv("FORWARD_CHANNEL_ID", "-1003056741244")  # <-- ОСТАВЛЯЮ КАК ТЫ ПРОСИЛ
# Твой user_id для дубля в ЛС (узнать у @userinfobot). Можно оставить пустым.
_owner_env = os.getenv("OWNER_USER_ID", "253552649").strip()
OWNER_USER_ID = int(_owner_env) if _owner_env.isdigit() else None  # <-- ОСТАВЛЯЮ 253552649

DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Пул потоков для I/O yt_dlp
executor = ThreadPoolExecutor(max_workers=4)

# ================== УТИЛИТЫ ==================
# Любой http(s) URL — для канала обрабатываем только прямые ссылки
URL_ANY_RE = re.compile(r'https?://\S+', re.I)
# Для ЛС — распознаём ютуб/саундклауд как "прямые ссылки", остальное пойдёт в поиск
URL_YT_SC_RE = re.compile(r'https?://(soundcloud\.com|snd\.sc|youtu\.be|(?:www\.)?youtube\.com)/', re.I)

def sanitize_filename(filename: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

def extract_first_url_from_message(msg) -> str | None:
    """
    Достаёт первый URL из message:
    - из entities/text_link (text)
    - из caption_entities/text_link (caption)
    - из plain-текста/подписи по regex
    """
    # 1) entities (текст)
    if getattr(msg, "entities", None):
        text = msg.text or ""
        for ent in msg.entities:
            if ent.type == "text_link" and ent.url:
                return ent.url
            if ent.type == "url":
                return text[ent.offset: ent.offset + ent.length]

    # 2) caption_entities (подпись)
    if getattr(msg, "caption_entities", None):
        cap = msg.caption or ""
        for ent in msg.caption_entities:
            if ent.type == "text_link" and ent.url:
                return ent.url
            if ent.type == "url":
                return cap[ent.offset: ent.offset + ent.length]

    # 3) plain regex из текста и подписи
    for s in (msg.text or "", msg.caption or ""):
        m = URL_ANY_RE.search(s)
        if m:
            return m.group(0)
    return None

# ================== СКАЧИВАНИЕ ==================
def download_track(url: str):
    """
    Скачивает аудио (YouTube/SoundCloud/и т.п.) и конвертит в mp3 (128).
    Возвращает (путь_к_mp3, title) или (None, None)
    """
    unique_filename = str(uuid.uuid4())
    temp_path = os.path.join(DOWNLOAD_DIR, unique_filename)

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_path,
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,

        # Устойчивость
        'retries': 3,
        'fragment_retries': 3,
        'socket_timeout': 15,
        'geo_bypass': True,
        'nocheckcertificate': True,

        # YouTube нюансы
        'extract_flat': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'web'],  # помогает против "No formats"
            }
        },
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,

        # Конвертация в MP3
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                logger.error("yt_dlp вернул None для url=%s", url)
                return None, None
            # Если плейлист/коллекция — берём первый элемент
            if isinstance(info, dict) and info.get('entries'):
                info = info['entries'][0]
            title = info.get('title') or 'Unknown'
        final_file = f"{temp_path}.mp3"
        if not os.path.exists(final_file):
            logger.warning("Файл не найден: %s", final_file)
            return None, None
        return final_file, sanitize_filename(title)
    except Exception as e:
        logger.error("Ошибка при скачивании (%s): %s", url, e)
        return None, None

# ================== ОТПРАВКА ==================
async def send_audio_dual(
    context: ContextTypes.DEFAULT_TYPE,
    primary_chat_id: int | str,           # кому шлём в первую очередь
    secondary_chat_id: int | str | None,  # куда продублировать (или None)
    file_path: str,
    title: str,
    caption_for_channel: str | None = None,
    to_channel_first: bool = False,
):
    """
    Отправляет аудио в два места без второй загрузки:
      - первая отправка: загрузка файла (получаем file_id)
      - вторая отправка: по file_id
    Если secondary_chat_id = None — шлём только в primary.
    Если to_channel_first=True — сначала в канал (CHANNEL_ID), затем во secondary_chat_id.
    """
    async def _send_file(chat_id):
        with open(file_path, 'rb') as f:
            return await context.bot.send_audio(
                chat_id=chat_id,
                audio=InputFile(f, filename=f"{title}.mp3"),
                title=title,
                caption=(caption_for_channel if (str(chat_id) == str(CHANNEL_ID) and caption_for_channel) else None)
            )

    if secondary_chat_id is None:
        await _send_file(primary_chat_id)
        return

    # ВАЖНО: корректный порядок адресатов
    if to_channel_first:
        first_id = CHANNEL_ID            # сначала в канал
        second_id = secondary_chat_id    # потом во второго (например, OWNER_USER_ID)
    else:
        first_id = primary_chat_id       # сначала инициатор (ЛС)
        second_id = secondary_chat_id    # потом во второго (канал)

    # 1) первая отправка (загрузка файла)
    msg = await _send_file(first_id)
    file_id = msg.audio.file_id if msg and msg.audio else None

    # 2) вторая отправка по file_id (или повторная загрузка, если не вышло)
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

# ================== ХЭНДЛЕРЫ ЛС ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Отправь название песни или ссылку (YouTube/SoundCloud). Я пришлю трек и опубликую в канале.")

async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if not text:
        return

    # Если прямой URL (YouTube/SoundCloud) — скачиваем «тихо» и шлём
    if URL_YT_SC_RE.search(text):
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(executor, partial(download_track, text))
        if not file_path or not os.path.exists(file_path):
            await update.effective_chat.send_message("Не удалось скачать. Попробуй другую ссылку.")
            return

        try:
            # Сначала юзеру, потом в канал по file_id
            await send_audio_dual(
                context=context,
                primary_chat_id=update.effective_chat.id,
                secondary_chat_id=int(CHANNEL_ID) if str(CHANNEL_ID).lstrip("-").isdigit() else CHANNEL_ID,
                file_path=file_path,
                title=title,
                caption_for_channel=f"🎵 {title}",
                to_channel_first=False
            )
        finally:
            try:
                os.remove(file_path)
            except Exception as e:
                logger.error("Ошибка удаления файла %s: %s", file_path, e)
        return

    # Иначе — YouTube-поиск (тихо). Покажем 3 варианта.
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True,
            'extract_flat': 'in_playlist',
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
            'no_color': True,
            'socket_timeout': 3,
            'retries': 1,
        }
        info = await asyncio.get_event_loop().run_in_executor(
            executor,
            lambda: YoutubeDL(ydl_opts).extract_info(f"ytsearch3:{text}", download=False, ie_key='YoutubeSearch')
        )
        entries = (info or {}).get('entries', [])
        if not entries:
            await update.message.reply_text('Ничего не найдено.')
            return

        buttons = []
        for idx, entry in enumerate(entries[:3]):
            title = entry.get('title', 'Unknown title')
            vid = entry.get('id', '')
            buttons.append((f"{idx+1}. {title[:40]}", vid))

        keyboard = [[InlineKeyboardButton(text=b[0], callback_data=b[1])] for b in buttons]
        await update.message.reply_text('Выбери вариант:', reply_markup=InlineKeyboardMarkup(keyboard))

    except Exception as e:
        logger.error('Ошибка при поиске: %s', e)
        await update.message.reply_text('Ошибка при поиске. Попробуй ещё раз.')

# Кнопки из поиска (ЛС)
async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()  # без edit_message_text — «тихо»
    video_id = query.data
    url = f"https://www.youtube.com/watch?v={video_id}"

    try:
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(executor, partial(download_track, url))
        if not file_path:
            await context.bot.send_message(chat_id=query.message.chat_id, text="Не удалось скачать. Попробуй другой трек.")
            return

        try:
            await send_audio_dual(
                context=context,
                primary_chat_id=query.message.chat_id,
                secondary_chat_id=int(CHANNEL_ID) if str(CHANNEL_ID).lstrip("-").isdigit() else CHANNEL_ID,
                file_path=file_path,
                title=title,
                caption_for_channel=f"🎵 {title}",
                to_channel_first=False
            )
        finally:
            try:
                os.remove(file_path)
                logger.info("Удалён: %s", file_path)
            except Exception as e:
                logger.error("Ошибка при удалении %s: %s", file_path, e)

    except Exception as e:
        logger.error("Ошибка при обработке аудио: %s", e)
        await context.bot.send_message(chat_id=query.message.chat_id, text="Ошибка. Попробуй ещё раз.")

# ================== ХЭНДЛЕР КАНАЛА ==================
async def channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Бот — админ канала. Если в канал публикуется пост со ССЫЛКОЙ,
    бот молча скачивает, публикует аудио в канал и (опционально) дублирует в ЛС OWNER_USER_ID.
    """
    msg = update.channel_post
    if not msg:
        return

    logger.info("channel_post: пришло сообщение в канал (chat_id=%s, message_id=%s)", msg.chat_id, msg.message_id)

    url = extract_first_url_from_message(msg)
    if not url:
        # Нет ссылки — тихо игнорируем
        return

    logger.info("channel_post: найден URL: %s", url)

    loop = asyncio.get_event_loop()
    file_path, title = await loop.run_in_executor(executor, partial(download_track, url))

    if not file_path or not os.path.exists(file_path):
        logger.error("channel_post: не удалось скачать (url=%s). Возможно, priv/лайв/регион/age.", url)
        return

    try:
        # Сначала в канал, потом — в ЛС владельцу (если указан OWNER_USER_ID)
        await send_audio_dual(
            context=context,
            primary_chat_id=int(CHANNEL_ID) if str(CHANNEL_ID).lstrip("-").isdigit() else CHANNEL_ID,
            secondary_chat_id=OWNER_USER_ID,    # 253552649
            file_path=file_path,
            title=title,
            caption_for_channel=f"🎵 {title}",
            to_channel_first=True
        )
    finally:
        try:
            os.remove(file_path)
        except Exception as e:
            logger.error("channel_post: не смог удалить tmp-файл: %s", e)

# ================== /myid (по желанию) ==================
async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Ваш user_id: {update.effective_user.id}")

# ================== MAIN ==================
def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Команды
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('myid', myid))

    # ЛС (текст + кнопки)
    application.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND, search_song))
    application.add_handler(CallbackQueryHandler(button))

    # Канал: ловим ЛЮБЫЕ посты (текст/медиа/подпись), разбирать URL будем сами
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL & ~filters.StatusUpdate.ALL, channel_post))

    # Важно: явно разрешаем channel_post
    application.run_polling(allowed_updates=["message", "callback_query", "channel_post"])

    # Очистка tmp при штатном завершении
    try:
        for fn in os.listdir(DOWNLOAD_DIR):
            path = os.path.join(DOWNLOAD_DIR, fn)
            if os.path.isfile(path):
                os.remove(path)
    except Exception as e:
        logger.error("Ошибка при удалении временных файлов: %s", e)

if __name__ == '__main__':
    main()
