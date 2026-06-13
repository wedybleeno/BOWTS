# BOTS - Коллекция ботов и скриптов

Коллекция различных ботов и скриптов для автоматизации задач.

## 📁 Структура проекта

### 🎵 Музыкальные боты
- `soundcloud.py` - Скрипт для сбора ссылок на треки из лайков SoundCloud
- `get_client_id.py` - Вспомогательный скрипт для получения client_id SoundCloud
- `muz.py`, `muz2.py`, `muz3.py` - Музыкальные боты
- `muzbot.py`, `muzbot2.py` - Telegram музыкальные боты
- `cutmusic.py` - Скрипт для обрезки музыки

### 🤖 Telegram боты
- `tele.py` - Telegram бот
- `telethon_listener.py` - Слушатель Telegram с использованием Telethon
- `cryptobot.py` - Криптовалютный бот

### 🎬 Видео обработка
- `veo.py` - Скрипт для работы с видео
- `make_video.py` - Создание видео

### 🌐 Веб-приложения
- `main6.py` - Основное веб-приложение
- `client_gui.py` - GUI клиент
- `server1.py`, `server2.py`, `server3.py` - Серверные приложения

### 🔧 Утилиты
- `lan.py` - Сетевые утилиты
- `crypt.py` - Криптографические функции

## 🚀 Установка и запуск

### Требования
```bash
pip install -r requirements.txt
```

### Основные зависимости
- `requests` - HTTP запросы
- `urllib3` - HTTP клиент
- `python-telegram-bot` - Telegram Bot API
- `yt-dlp` - Скачивание видео
- `telethon` - Telegram клиент

## 📋 Использование

### SoundCloud скрипт
```bash
python soundcloud.py
```

### Получение client_id для SoundCloud
```bash
python get_client_id.py
```

### Telegram бот
```bash
python tele.py
```

## ⚙️ Настройка

1. Создайте файл `.env` с вашими токенами:
```
TELEGRAM_TOKEN=your_telegram_token
GOOGLE_API_KEY=your_google_api_key
```

2. Для SoundCloud скрипта замените `PROFILE_URL` в `soundcloud.py` на ваш профиль.

## 🔒 Безопасность

- Все токены и ключи исключены из репозитория через `.gitignore`
- Используйте переменные окружения для конфиденциальных данных
- Репозиторий приватный для защиты ваших данных

## 📝 Лицензия

Приватный проект. Все права защищены.

## 🤝 Поддержка

Для вопросов и предложений создавайте Issues в репозитории.
