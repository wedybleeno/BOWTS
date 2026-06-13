# BOTS - Collection of Bots and Scripts

A collection of various bots and scripts for task automation.

## 📁 Project Structure

### 🎵 Music Bots
- `soundcloud.py` - Script to scrape track links from SoundCloud likes.
- `get_client_id.py` - Helper script to fetch a SoundCloud `client_id`.
- `muz.py`, `muz2.py`, `muz3.py` - Music downloader bots.
- `muzbot.py`, `muzbot2.py` - Telegram music downloader bots.
- `cutmusic.py` - Script to trim/cut audio files.

### 🤖 Telegram Bots
- `tele.py` - Telegram channel search and indexing bot.
- `telethon_listener.py` - Telegram message listener using Telethon.
- `cryptobot.py` - Cryptocurrency bot integrated with Gemini AI.

### 🎬 Video Processing
- `veo.py` - Script to generate videos using Google Veo.
- `make_video.py` - Helper script to generate video from prompt.

### 🌐 Web & Networking Applications
- `main6.py` - Main web application.
- `client_gui.py` - GUI client.
- `server1.py`, `server2.py`, `server3.py` - Socket server scripts.

### 🔧 Utilities
- `lan.py` - Local network scanning utilities.
- `crypt.py` - Cryptographic helper functions.

## 🚀 Setup & Launch

### Requirements
Ensure Python is installed, then run:
```bash
pip install -r requirements.txt
```

### Key Dependencies
- `requests` - HTTP requests library.
- `urllib3` - HTTP client.
- `python-telegram-bot` - Telegram Bot API wrapper.
- `yt-dlp` - Advanced video and audio downloader.
- `telethon` - Telegram client library.
- `python-dotenv` - Environment variable manager.

## 📋 Usage

### SoundCloud Scraper
```bash
python soundcloud.py
```

### Extracting SoundCloud client_id
```bash
python get_client_id.py
```

### Running Telegram Bot
```bash
python tele.py
```

## ⚙️ Configuration

1. Create a `.env` file containing your API credentials:
```ini
TELEGRAM_TOKEN=your_telegram_token
GOOGLE_API_KEY=your_google_api_key
```

2. For the SoundCloud scraper, modify the `PROFILE_URL` in `soundcloud.py` to point to your profile.

## 🔒 Security

- All API tokens and credentials are excluded from Git history using `.gitignore`.
- Use the `.env` file to manage sensitive parameters locally.
- Keep the repository private if you host any sensitive custom keys.

## 📝 License

Private project. All rights reserved.

## 🤝 Contributing & Support

For bugs, questions, or feature requests, feel free to open an Issue in the repository.
