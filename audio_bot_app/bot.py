import os
import re
import logging
from yt_dlp import YoutubeDL
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Ваш токен
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения или .env")

# Директория для загрузок
DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# yt-dlp опции для поиска
YTDL_SEARCH_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "noplaylist": True,
    "skip_download": True,
    "socket_timeout": 5,
    "retries": 1,
}

# yt-dlp опции для загрузки
YTDL_DOWNLOAD_OPTS = {
    "format": "bestaudio[abr<=128]/bestaudio",
    "outtmpl": os.path.join(DOWNLOAD_DIR, "%(id)s.%(ext)s"),
    "quiet": True,
    "noplaylist": True,
    "postprocessors": [{
        "key": "FFmpegExtractAudio",
        "preferredcodec": "mp3",
        "preferredquality": "128",
    }],
}

def sanitize_filename(name: str) -> str:
    """Очищает имя файла от запрещенных символов"""
    return re.sub(r'[<>:\\"/\\|?*]', '_', name)


def search_youtube(query: str, max_results: int = 5):
    with YoutubeDL(YTDL_SEARCH_OPTS) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False)
    return info.get("entries", [])


def download_audio(video_url: str) -> str:
    """Скачивает аудио и возвращает путь к mp3-файлу с оригинальным именем"""
    with YoutubeDL(YTDL_DOWNLOAD_OPTS) as ydl:
        info = ydl.extract_info(video_url, download=True)
    video_id = info.get("id")
    title = info.get("title", video_id)
    safe_title = sanitize_filename(title)[:200]

    # Исходный путь по ID
    src = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    # Новый путь с оригинальным названием
    dst = os.path.join(DOWNLOAD_DIR, f"{safe_title}.mp3")

    try:
        os.replace(src, dst)
    except Exception as e:
        logger.warning(f"Не удалось переименовать файл: {e}")
        return src

    return dst

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! /search <запрос> — поиск, /download <URL> — прямая загрузка."
    )

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Укажи запрос: /search <текст>")
    q = " ".join(context.args)
    msg = await update.message.reply_text(f"Ищем «{q}»...")
    try:
        entries = search_youtube(q, max_results=3)
        if not entries:
            return await msg.edit_text("Ничего не нашли.")
        buttons = [
            [InlineKeyboardButton(e.get("title", "—")[:40], callback_data=e["id"])]
            for e in entries
        ]
        await msg.edit_text("Результаты:", reply_markup=InlineKeyboardMarkup(buttons))
    except Exception as e:
        logger.error("search error: %s", e)
        await msg.edit_text("Ошибка при поиске.")

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Укажи URL: /download <URL>")
    url = context.args[0]
    msg = await update.message.reply_text(f"Скачиваю {url}...")
    try:
        path = download_audio(url)
        await context.bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=open(path, "rb")
        )
        await msg.delete()
    except Exception as e:
        logger.error("download error: %s", e)
        await msg.edit_text("Ошибка при загрузке.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    vid = q.data
    url = f"https://www.youtube.com/watch?v={vid}"
    msg = await q.edit_message_text(f"Скачиваю {url}...")
    try:
        path = download_audio(url)
        await context.bot.send_audio(
            chat_id=update.effective_chat.id,
            audio=open(path, "rb")
        )
        await msg.delete()
    except Exception as e:
        logger.error("callback download error: %s", e)
        await msg.edit_message_text("Ошибка при загрузке.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("download", download_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
