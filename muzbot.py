import logging
import os
import re
import uuid
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
logging.basicConfig(level=logging.INFO)

def sanitize_filename(filename):
    """
    Очистка имени файла от небезопасных символов.
    """
    # Заменяем слеши и другие специальные символы на подчеркивание
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Отправь мне название песни или исполнителя, и я найду её для тебя.')

async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text('Пожалуйста, введите название песни или исполнителя.')
        return

    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'extract_flat': True,  # Avoid downloading the video
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch10:{query}", download=False)  # Fetch multiple results
            entries = info.get('entries', [])

        if not entries:
            await update.message.reply_text('Ничего не найдено.')
            return

        # Send the list of search results
        buttons = []
        for index, entry in enumerate(entries[:3]):  # Limit to the first 3 results
            title = entry.get('title', 'Unknown title')
            button_text = f"{index + 1}. {title}"
            buttons.append((button_text, entry.get('url', '')))

        # Create inline keyboard
        keyboard = [[InlineKeyboardButton(text=btn[0], callback_data=btn[1])] for btn in buttons]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Выберите один из вариантов:', reply_markup=reply_markup)

    except Exception as e:
        logging.error(f'Error during search: {e}')
        await update.message.reply_text(f'Произошла ошибка при поиске: {e}')

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    song_url = query.data

    if not song_url:
        await query.edit_message_text(text="Выбор недействителен.")
        return

    try:
        # Generate a unique filename to avoid conflicts
        unique_filename = str(uuid.uuid4())
        temp_file_path = os.path.join(DOWNLOAD_DIR, f"{unique_filename}.webm")

        ydl_opts = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'outtmpl': temp_file_path,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(song_url, download=True)

        # Rename the downloaded file
        original_title = info['title']
        sanitized_title = sanitize_filename(original_title)
        downloaded_file_path = temp_file_path.replace('.webm', '.mp3')
        new_file_path = os.path.join(DOWNLOAD_DIR, f"{sanitized_title}.mp3")

        if os.path.exists(downloaded_file_path):
            os.rename(downloaded_file_path, new_file_path)
            logging.info(f'Renamed file: {downloaded_file_path} to {new_file_path}')
        else:
            logging.warning(f'File to rename not found: {downloaded_file_path}')
            new_file_path = downloaded_file_path  # fallback to downloaded file path if renaming failed

        # Check if file exists
        if not os.path.exists(new_file_path):
            await query.edit_message_text(text='Ошибка при скачивании или конвертации файла.')
            logging.error(f'File does not exist after renaming: {new_file_path}')
            return

        # Send the mp3 file
        with open(new_file_path, 'rb') as mp3_file:
            await query.message.reply_document(document=InputFile(mp3_file, filename=f'{sanitized_title}.mp3'))

        # Remove the mp3 file after sending
        os.remove(new_file_path)
        logging.info(f'File sent and deleted: {new_file_path}')

    except Exception as e:
        logging.error(f'Error during file handling: {e}')
        await query.edit_message_text(text=f'Произошла ошибка при отправке файла: {e}')

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_song))
    application.add_handler(CallbackQueryHandler(button))

    application.run_polling()

if __name__ == '__main__':
    main()
