import sys
import os
import json
import shutil
import threading
import uuid
import re
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from yt_dlp import YoutubeDL
from dotenv import load_dotenv

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import QUrl, Qt
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem,
    QPushButton, QWidget, QHBoxLayout, QVBoxLayout,
    QFileDialog, QLineEdit, QMessageBox, QInputDialog, QMenu, QLabel
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from telegram import Bot, Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CallbackContext

# --- Настройка директорий и метаданных ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_TOKEN:
    raise RuntimeError("Положите TELEGRAM_BOT_TOKEN в .env")

AUDIO_DIR = "audio_files"
SPLIT_DIR = "splits"
META_FILE = "categories.json"
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(SPLIT_DIR, exist_ok=True)

if os.path.exists(META_FILE):
    with open(META_FILE, "r", encoding="utf-8") as f:
        categories = json.load(f)
else:
    categories = {}

def save_meta():
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(categories, f, ensure_ascii=False, indent=2)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

# --- Функции работы с youtube-dl ---
def search_youtube(query, max_results=3):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'noplaylist': True,
        'skip_download': True,
        'socket_timeout': 5,
        'retries': 1,
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{max_results}:{query}", download=False, ie_key='YoutubeSearch')
    return [{'id': e['id'], 'title': e.get('title','')} for e in info.get('entries', [])]

def download_audio_from_url(url):
    """
    Скачивает аудио по прямой ссылке (YouTube или другой поддерживаемой).
    """
    uid = str(uuid.uuid4())
    outtmpl = os.path.join(AUDIO_DIR, uid)
    ydl_opts = {
        'format': 'bestaudio[abr<=128]/bestaudio',
        'outtmpl': outtmpl,
        'quiet': True,
        'noplaylist': True,
        'socket_timeout': 10,
        'retries': 1,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    title = info.get('title', uid)
    mp3_path = outtmpl + ".mp3"
    if not os.path.exists(mp3_path):
        return None, None
    clean = sanitize_filename(title)
    final_fn = clean + ".mp3"
    final_path = os.path.join(AUDIO_DIR, final_fn)
    os.replace(mp3_path, final_path)
    return final_path, final_fn

# --- Диалог результатов поиска ---
class SearchResultsDialog(QtWidgets.QDialog):
    def __init__(self, entries, on_select, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Search results")
        vbox = QVBoxLayout(self)
        for e in entries:
            h = QHBoxLayout()
            lbl = QLabel(e['title'])
            btn = QPushButton("Download")
            btn.clicked.connect(lambda _, vid=e['id']: self.select(vid))
            h.addWidget(lbl)
            h.addStretch()
            h.addWidget(btn)
            vbox.addLayout(h)
        self.on_select = on_select
        self.setLayout(vbox)
        self.resize(500, 200)
    def select(self, video_id):
        self.on_select(video_id)
        self.accept()

# --- Главное окно приложения ---
class AudioBotApp(QMainWindow):
    new_audio = QtCore.pyqtSignal(str)
    new_search_results = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Audio Browser")
        self.resize(800, 600)

        # Поля поиска и ссылки
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search song/book…")
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.on_search)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL to download…")
        self.url_btn = QPushButton("Download URL")
        self.url_btn.clicked.connect(self.on_download_url)

        # Поле для chat_id
        self.chat_id_input = QLineEdit()
        self.chat_id_input.setPlaceholderText("Chat ID for Send…")

        # Дерево объектов
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["File", "Play", "Download", "Send"])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)

        # Плеер
        self.player = QMediaPlayer()

        # Компоновка UI
        top_h = QHBoxLayout()
        top_h.addWidget(self.search_input)
        top_h.addWidget(self.search_btn)
        top_h.addWidget(self.url_input)
        top_h.addWidget(self.url_btn)
        top_h.addWidget(self.chat_id_input)

        layout = QVBoxLayout()
        layout.addLayout(top_h)
        layout.addWidget(self.tree)

        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # ThreadPool
        self.executor = ThreadPoolExecutor(max_workers=2)

        # Сигналы
        self.new_audio.connect(self.reload_tree)
        self.new_search_results.connect(self.show_search_results)

        # Загрузка существующих
        os.makedirs(AUDIO_DIR, exist_ok=True)
        self.reload_tree()

        # Запуск Telegram-поллинга
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, self.handle_msg))
        threading.Thread(target=app.run_polling, daemon=True).start()

    # --- Поиск ---
    def on_search(self):
        q = self.search_input.text().strip()
        if not q: return
        self.search_btn.setEnabled(False)
        self.executor.submit(self._search_task, q)

    def _search_task(self, query):
        try:
            results = search_youtube(query)
        except Exception:
            results = []
        self.new_search_results.emit(results)

    def show_search_results(self, entries):
        self.search_btn.setEnabled(True)
        if not entries:
            QMessageBox.information(self, "No results", "Nothing found.")
            return
        dlg = SearchResultsDialog(entries, self.download_from_search, self)
        dlg.exec_()

    def download_from_search(self, video_id):
        self.executor.submit(self._download_task, video_id)

    def _download_task(self, video_id):
        path, fn = download_audio_from_url(f"https://www.youtube.com/watch?v={video_id}")
        if path:
            categories[fn] = "music"
            save_meta()
            self.new_audio.emit(fn)
        else:
            QtCore.QMetaObject.invokeMethod(self, lambda: QMessageBox.critical(self, "Error", "Download failed."), Qt.QueuedConnection)

    # --- Загрузка по URL ---
    def on_download_url(self):
        url = self.url_input.text().strip()
        if not url: return
        self.url_btn.setEnabled(False)
        self.executor.submit(self._download_url_task, url)

    def _download_url_task(self, url):
        path, fn = download_audio_from_url(url)
        if path:
            categories[fn] = "music"
            save_meta()
            self.new_audio.emit(fn)
        else:
            QtCore.QMetaObject.invokeMethod(self, lambda: QMessageBox.critical(self, "Error", "Download failed."), Qt.QueuedConnection)
        QtCore.QMetaObject.invokeMethod(self.url_btn, lambda: self.url_btn.setEnabled(True), Qt.QueuedConnection)

    # --- Дерево файлов и операции ---
    def reload_tree(self):
        self.tree.clear()
        music = QTreeWidgetItem(self.tree, ["Музыка"])
        books = QTreeWidgetItem(self.tree, ["Аудиокниги"])
        for fn in sorted(os.listdir(AUDIO_DIR)):
            if not fn.lower().endswith(".mp3"): continue
            cat = categories.get(fn, "music")
            parent = books if cat=="audiobook" else music
            it = QTreeWidgetItem(parent, [fn])
            for col,name in enumerate(("Play","Download","Send"),1):
                btn = QPushButton(name)
                getattr(self, f"{name.lower()}_clicked")(btn, fn)
                self.tree.setItemWidget(it, col, btn)
        self.tree.expandAll()

    def play_clicked(self, btn, fn): btn.clicked.connect(lambda: self.play(fn))
    def download_clicked(self, btn, fn): btn.clicked.connect(lambda: self.download(fn))
    def send_clicked(self, btn, fn): btn.clicked.connect(lambda: self.send(fn))

    def play(self, fn):
        url = QUrl.fromLocalFile(os.path.join(AUDIO_DIR, fn))
        self.player.setMedia(QMediaContent(url))
        self.player.play()

    def download(self, fn):
        src = os.path.join(AUDIO_DIR, fn)
        dst, _ = QFileDialog.getSaveFileName(self, "Save As", fn)
        if dst: shutil.copy(src, dst)

    def send(self, fn):
        cid = self.chat_id_input.text().strip()
        if not cid:
            QMessageBox.warning(self, "Error", "Введите Chat ID")
            return
        bot = Bot(token=TELEGRAM_TOKEN)
        path = os.path.join(AUDIO_DIR, fn)
        with open(path, 'rb') as f:
            if fn.lower().endswith(".ogg"):
                bot.send_voice(chat_id=cid, voice=f)
            else:
                bot.send_audio(chat_id=cid, audio=f)
        QMessageBox.information(self, "Sent", f"{fn} отправлен")

    def handle_msg(self, update: Update, context: CallbackContext):
        msg = update.message
        if msg.audio:
            file = msg.audio.get_file()
            fn = msg.audio.file_name or f"{msg.audio.file_id}.mp3"
        else:
            file = msg.voice.get_file()
            fn = f"{msg.voice.file_id}.ogg"
        path = os.path.join(AUDIO_DIR, fn)
        if not os.path.exists(path):
            file.download(path)
            if fn not in categories:
                categories[fn] = "music"
                save_meta()
            self.new_audio.emit(fn)

    def on_context_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or not it.parent(): return
        fn = it.text(0)
        menu = QMenu()
        m1 = menu.addAction("Mark as Music")
        m2 = menu.addAction("Mark as Audiobook")
        if categories.get(fn)=="audiobook":
            m3 = menu.addAction("Split audiobook…")
        act = menu.exec_(self.tree.viewport().mapToGlobal(pos))
        if act==m1:
            categories[fn]="music"; save_meta(); self.reload_tree()
        elif act==m2:
            categories[fn]="audiobook"; save_meta(); self.reload_tree()
        elif 'm3' in locals() and act==m3:
            self.split_dialog(fn)

    def split_dialog(self, fn):
        mins, ok = QInputDialog.getInt(self, "Split", "Minutes per part:", value=10, min=1, max=120)
        if not ok: return
        from pydub import AudioSegment
        src = os.path.join(AUDIO_DIR, fn)
        audio = AudioSegment.from_file(src)
        ms = mins*60*1000
        base, _ = os.path.splitext(fn)
        for i, st in enumerate(range(0, len(audio), ms), 1):
            part = audio[st:st+ms]
            out = os.path.join(SPLIT_DIR, f"{base}_part{i}.mp3")
            part.export(out, format="mp3")
        QMessageBox.information(self, "Done", f"Split into parts in {SPLIT_DIR}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AudioBotApp()
    w.show()
    sys.exit(app.exec_())
