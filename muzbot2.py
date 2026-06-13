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
    # Заменяем слеши и другие специальные символы на подчеркивание
    return re.sub(r'[<>:"/\\|?*]', '_', filename)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Привет! Отправь мне название песни или исполнителя, и я найду её для тебя.')

async def search_song(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.message.text.strip()
    if not query:
        await update.message.reply_text('Пожалуйста, введите название песни или исполнителя.')
        return

    # Отправить "печатает сообщение" для обратной связи
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="typing")

    try:
        # Быстрые настройки для поиска, минимизирующие количество запросов
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'skip_download': True,
            'extract_flat': 'in_playlist',  # Быстрее чем True
            'youtube_include_dash_manifest': False,
            'youtube_include_hls_manifest': False,
            'no_color': True,
            'socket_timeout': 3,  # Сокращаем таймаут для быстрого ответа
            'retries': 1,
        }

        # Запускаем поиск в отдельном потоке
        loop = asyncio.get_event_loop()
        
        # Это выполняется в отдельном потоке, не блокируя бота
        async def search_yt():
            with YoutubeDL(ydl_opts) as ydl:
                # Явно указываем IE для YouTube, чтобы избежать лишнего определения
                return ydl.extract_info(f"ytsearch3:{query}", download=False, ie_key='YoutubeSearch')
                
        info = await loop.run_in_executor(executor, lambda: YoutubeDL(ydl_opts).extract_info(f"ytsearch3:{query}", download=False, ie_key='YoutubeSearch'))
        entries = info.get('entries', [])

        if not entries:
            await update.message.reply_text('Ничего не найдено.')
            return

        # Отправляем результаты
        buttons = []
        for index, entry in enumerate(entries[:3]):
            title = entry.get('title', 'Unknown title')
            button_text = f"{index + 1}. {title[:40]}"
            callback_data = entry.get('id', '')
            buttons.append((button_text, callback_data))

        # Создаем клавиатуру с кнопками
        keyboard = [[InlineKeyboardButton(text=btn[0], callback_data=btn[1])] for btn in buttons]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('Выберите один из вариантов:', reply_markup=reply_markup)

    except Exception as e:
        logger.error(f'Ошибка при поиске: {e}')
        await update.message.reply_text(f'Произошла ошибка при поиске. Пожалуйста, попробуйте еще раз.')

def download_audio(video_id):
    """
    Функция для загрузки аудио, запускается в отдельном потоке
    """
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    # Создаем уникальное имя файла для загрузки
    unique_filename = str(uuid.uuid4())
    temp_file_path = os.path.join(DOWNLOAD_DIR, f"{unique_filename}")
    
    # Оптимизированные настройки для yt-dlp, чтобы ускорить извлечение информации
    ydl_opts = {
        # Оптимизированный формат - берем только аудио с нужным битрейтом
        'format': 'bestaudio[abr<=128]/bestaudio',
        'noplaylist': True,
        'outtmpl': temp_file_path,
        'quiet': True,
        
        # Пропускаем лишние извлечения данных
        'skip_download_archive': True,
        'no_warnings': True,
        'no_color': True,
        'geo_bypass': True,
        'ignore_no_formats_error': True,
        'ignore_error': True,
        
        # Ускоряем сетевое взаимодействие
        'socket_timeout': 10,
        'retries': 1,  # Уменьшено количество повторных попыток
        'fragment_retries': 1,
        
        # Указываем yt-dlp обрабатывать только одну часть информации за раз
        'extract_flat': False,
        'youtube_include_dash_manifest': False, 
        'youtube_include_hls_manifest': False,
        
        # Постпроцессинг (кодирование в mp3)
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }
    
    try:
        # Используем опцию --no-check-certificate для обхода проверки сертификатов
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True, ie_key='Youtube')
            title = info.get('title', 'Unknown')
        
        # Находим скачанный файл
        downloaded_file_path = f"{temp_file_path}.mp3"
        if not os.path.exists(downloaded_file_path):
            logger.warning(f"Скачанный файл не найден: {downloaded_file_path}")
            return None, None
        
        sanitized_title = sanitize_filename(title)
        return downloaded_file_path, sanitized_title
    except Exception as e:
        logger.error(f"Ошибка при загрузке аудио: {e}")
        return None, None

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Получаем ID видео из данных кнопки
    video_id = query.data
    
    # Информируем пользователя о начале загрузки
    await query.edit_message_text(text="Скачиваю трек...")
    
    # Используем действие "upload_document" для индикации загрузки
    await context.bot.send_chat_action(chat_id=update.effective_message.chat_id, action="upload_document")
    
    try:
        # Запускаем загрузку в отдельном потоке
        loop = asyncio.get_event_loop()
        file_path, title = await loop.run_in_executor(
            executor,
            partial(download_audio, video_id)
        )
        
        if not file_path or not os.path.exists(file_path):
            await query.edit_message_text(text="Ошибка при скачивании. Пожалуйста, попробуйте другую песню.")
            return
        
        # Отправляем файл
        with open(file_path, 'rb') as audio_file:
            await context.bot.send_audio(
                chat_id=update.effective_message.chat_id,
                audio=InputFile(audio_file, filename=f"{title}.mp3"),
                title=title
            )
        
        # Обновляем сообщение
        await query.edit_message_text(text=f"✅ Готово!")
        
        # Удаляем временный файл после отправки
        os.remove(file_path)
        logger.info(f"Файл отправлен и удален: {file_path}")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке аудио: {e}")
        await query.edit_message_text(text="Произошла ошибка. Пожалуйста, попробуйте еще раз.")

def main():
    # Настраиваем приложение с более высоким лимитом на размер файлов
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Настройка обработчиков
    application.add_handler(CommandHandler('start', start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_song))
    application.add_handler(CallbackQueryHandler(button))
    
    # Запускаем бота
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    
    # Очистка временных файлов при завершении
    for filename in os.listdir(DOWNLOAD_DIR):
        file_path = os.path.join(DOWNLOAD_DIR, filename)
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
        except Exception as e:
            logger.error(f"Ошибка при удалении временного файла {file_path}: {e}")

if __name__ == '__main__':
    main()