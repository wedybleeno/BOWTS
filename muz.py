import logging
import os
import re
import uuid
import asyncio
from functools import partial
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from yt_dlp import YoutubeDL

from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Ваш API токен для Telegram
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN не задан в переменных окружения или .env")

# Путь к папке для хранения скачанных файлов
DOWNLOAD_DIR = 'downloads'
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Настройка логирования
logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Создаем пул потоков для параллельной обработки
executor = ThreadPoolExecutor(max_workers=4)

def sanitize_filename(filename):
    """
    Очистка имени файла от небезопасных символов.
    """
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Отправь мне название песни, ссылку YouTube или SoundCloud, и я найду её для тебя.')

async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text('Пожалуйста, введите название песни, YouTube или SoundCloud ссылку.')
        return

    # Если это ссылка SoundCloud или полная ссылка YouTube, сразу скачиваем
    if re.match(r'https?://(soundcloud\.com|snd\.sc)/', query) or re.match(r'https?://(www\.)?youtu', query):
        await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
        await update.message.reply_text('Скачиваю трек по ссылке...')
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(
            executor,
            partial(download_track, query)
        )
        if not file_path or not os.path.exists(file_path):
            await update.message.reply_text('Ошибка при скачивании по ссылке. Попробуйте другую.')
            return
        with open(file_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=update.effective_message.chat_id,
                audio=InputFile(audio_file, filename=f"{title}.mp3"),
                title=title
            )
        os.remove(file_path)
        return

    # Иначе выполняем поиск на YouTube
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")
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
            lambda: YoutubeDL(ydl_opts).extract_info(f"ytsearch3:{query}", download=False, ie_key='YoutubeSearch')
        )
        entries = info.get('entries', [])

        if not entries:
            await update.message.reply_text('Ничего не найдено.')
            return

        buttons = []
        for index, entry in enumerate(entries[:3]):
            title = entry.get('title', 'Unknown title')
            callback_data = entry.get('id', '')
            buttons.append((f"{index+1}. {title[:40]}", callback_data))

        keyboard = [[InlineKeyboardButton(text=btn[0], callback_data=btn[1])] for btn in buttons]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Выберите один из вариантов:', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f'Ошибка при поиске: {e}')
        await update.message.reply_text('Произошла ошибка при поиске. Пожалуйста, попробуйте еще раз.')


def download_track(url):
    """
    Скачиваем аудио по ссылке (YouTube или SoundCloud)
    """
    unique_filename = str(uuid.uuid4())
    temp_path = os.path.join(DOWNLOAD_DIR, unique_filename)
    ydl_opts = {
        'format': 'bestaudio[abr<=128]/bestaudio',
        'outtmpl': temp_path,
        'noplaylist': True,
        'quiet': True,
        'skip_download_archive': True,
        'no_warnings': True,
        'no_color': True,
        'geo_bypass': True,
        'ignore_no_formats_error': True,
        'ignore_error': True,
        'socket_timeout': 10,
        'retries': 1,
        'fragment_retries': 1,
        'extract_flat': False,
        'youtube_include_dash_manifest': False,
        'youtube_include_hls_manifest': False,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            title = info.get('title', 'Unknown')
        final_file = f"{temp_path}.mp3"
        if not os.path.exists(final_file):
            logger.warning(f"Файл не найден: {final_file}")
            return None, None
        return final_file, sanitize_filename(title)
    except Exception as e:
        logger.error(f"Ошибка при скачивании: {e}")
        return None, None

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    video_id = query.data
    await query.edit_message_text(text="Скачиваю трек...")
    await context.bot.send_chat_action(chat_id=query.message.chat_id, action="upload_document")
    try:
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(
            executor,
            partial(download_track, f"https://www.youtube.com/watch?v={video_id}")
        )
        if not file_path:
            await query.edit_message_text(text="Ошибка при скачивании. Пожалуйста, попробуйте другую песню.")
            return
        with open(file_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=InputFile(audio_file, filename=f"{title}.mp3"),
                title=title
            )
        await query.edit_message_text(text="✅ Готово!")
        os.remove(file_path)
        logger.info(f"Удален: {file_path}")
    except Exception as e:
        logger.error(f"Ошибка при обработке аудио: {e}")
        await query.edit_message_text(text="Произошла ошибка. Пожалуйста, попробуйте еще раз.")


def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_song))
    application.add_handler(CallbackQueryHandler(button))
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    # Очистка при завершении
    for fn in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, fn)
        try:
            if os.path.isfile(path): os.remove(path)
        except Exception as e:
            logger.error(f"Ошибка при удалении {path}: {e}")

if __name__ == '__main__':
    main()
