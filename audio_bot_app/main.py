import sys
import os
import json
import shutil
import threading
import uuid
import re
import time
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from yt_dlp import YoutubeDL
from dotenv import load_dotenv

from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtCore import QUrl, Qt, QTimer, pyqtSlot
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QTreeWidget, QTreeWidgetItem,
    QPushButton, QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
    QFileDialog, QLineEdit, QMessageBox, QInputDialog, QMenu, QLabel,
    QSlider, QStyle, QComboBox, QSpinBox, QTabWidget, QSplitter,
    QProgressBar, QToolButton, QGroupBox, QDialog, QFormLayout,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextEdit
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QPalette

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
PLAYLIST_DIR = "playlists"
THEMES = {
    "light": {
        "background": "#f5f5f5",
        "foreground": "#212121",
        "accent": "#3498db",
        "secondary": "#e0e0e0",
        "highlight": "#2980b9",
    },
    "dark": {
        "background": "#2d2d2d",
        "foreground": "#e0e0e0",
        "accent": "#3498db",
        "secondary": "#3d3d3d",
        "highlight": "#2980b9",
    }
}

# Создаем все необходимые директории
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(SPLIT_DIR, exist_ok=True)
os.makedirs(PLAYLIST_DIR, exist_ok=True)

# Загрузка метаданных
if os.path.exists(META_FILE):
    with open(META_FILE, "r", encoding="utf-8") as f:
        categories = json.load(f)
else:
    categories = {}

# Структура метаданных: {
#   "filename.mp3": {
#     "category": "music|audiobook|podcast", 
#     "title": "Название",
#     "artist": "Исполнитель",
#     "album": "Альбом",
#     "tags": ["тег1", "тег2"],
#     "rating": 0-5,
#     "bookmark": position_in_seconds
#   }
# }

def save_meta():
    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(categories, f, ensure_ascii=False, indent=2)

def sanitize_filename(name):
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def format_time(ms):
    """Форматирует время в мс в формат MM:SS"""
    s = round(ms / 1000)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

# --- Функции работы с youtube-dl ---
def search_youtube(query, max_results=5):
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
    return [{'id': e['id'], 'title': e.get('title',''), 'duration': e.get('duration', 0)} for e in info.get('entries', [])]

def download_audio_from_url(url, category="music", callback=None):
    """
    Скачивает аудио по ссылке с возможностью отслеживания прогресса
    """
    uid = str(uuid.uuid4())
    outtmpl = os.path.join(AUDIO_DIR, uid)
    
    def progress_hook(d):
        if callback and d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').strip()
            try:
                percent = float(p.replace('%', ''))
                callback(percent)
            except:
                pass
    
    ydl_opts = {
        'format': 'bestaudio[abr<=128]/bestaudio',
        'outtmpl': outtmpl,
        'quiet': True,
        'noplaylist': True,
        'socket_timeout': 10,
        'retries': 2,
        'progress_hooks': [progress_hook],
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '128',
        }],
    }
    
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
    
    title = info.get('title', uid)
    artist = info.get('artist', '')
    album = info.get('album', '')
    duration = info.get('duration', 0)
    
    mp3_path = outtmpl + ".mp3"
    if not os.path.exists(mp3_path):
        return None, None
    
    clean = sanitize_filename(title)
    final_fn = clean + ".mp3"
    final_path = os.path.join(AUDIO_DIR, final_fn)
    os.replace(mp3_path, final_path)
    
    # Сохраняем метаданные
    categories[final_fn] = {
        "category": category,
        "title": title,
        "artist": artist,
        "album": album,
        "duration": duration,
        "tags": [],
        "rating": 0,
        "bookmark": 0
    }
    save_meta()
    
    return final_path, final_fn

# --- Диалог результатов поиска с прогрессом скачивания ---
class SearchResultsDialog(QtWidgets.QDialog):
    def __init__(self, entries, on_select, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Результаты поиска")
        self.setMinimumWidth(600)
        self.setMinimumHeight(300)
        
        vbox = QVBoxLayout(self)
        
        # Таблица результатов
        self.table = QTableWidget(len(entries), 3)
        self.table.setHorizontalHeaderLabels(["Название", "Длительность", ""])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        
        for i, e in enumerate(entries):
            title_item = QTableWidgetItem(e['title'])
            duration_item = QTableWidgetItem(format_time(e['duration'] * 1000) if e['duration'] else "")
            
            self.table.setItem(i, 0, title_item)
            self.table.setItem(i, 1, duration_item)
            
            # Создаем виджет с кнопкой и прогрессбаром
            widget = QWidget()
            layout = QHBoxLayout(widget)
            layout.setContentsMargins(5, 2, 5, 2)
            
            download_btn = QToolButton()
            download_btn.setIcon(QIcon.fromTheme("download", QIcon(QApplication.style().standardIcon(QStyle.SP_ArrowDown))))
            download_btn.setToolTip("Скачать")
            download_btn.clicked.connect(lambda _, idx=i, vid=e['id']: self.select(idx, vid))
            
            self.progress_bar = QProgressBar()
            self.progress_bar.setTextVisible(False)
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(0)
            self.progress_bar.setMaximumWidth(100)
            self.progress_bar.setVisible(False)
            
            layout.addWidget(download_btn)
            layout.addWidget(self.progress_bar)
            layout.addStretch()
            
            widget.setLayout(layout)
            self.table.setCellWidget(i, 2, widget)
        
        vbox.addWidget(self.table)
        
        self.on_select = on_select
        self.setLayout(vbox)
        self.current_row = -1
        
    def select(self, row, video_id):
        self.current_row = row
        progress_widget = self.table.cellWidget(row, 2)
        progress_widget.findChild(QToolButton).setEnabled(False)
        progress_widget.findChild(QProgressBar).setVisible(True)
        
        self.on_select(video_id, self.update_progress)
    
    def update_progress(self, percent):
        if self.current_row >= 0:
            progress_widget = self.table.cellWidget(self.current_row, 2)
            progress_bar = progress_widget.findChild(QProgressBar)
            progress_bar.setValue(int(percent))
            
            if percent >= 100:
                # Закрываем диалог когда закончится скачивание
                QtCore.QTimer.singleShot(1000, self.accept)

class MetadataDialog(QtWidgets.QDialog):
    def __init__(self, filename, metadata, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Метаданные: {filename}")
        self.filename = filename
        self.metadata = metadata or {
            "category": "music",
            "title": filename,
            "artist": "",
            "album": "",
            "tags": [],
            "rating": 0,
            "bookmark": 0
        }
        
        layout = QFormLayout(self)
        
        # Категория
        self.category_combo = QComboBox()
        self.category_combo.addItems(["music", "audiobook", "podcast"])
        self.category_combo.setCurrentText(self.metadata.get("category", "music"))
        layout.addRow("Категория:", self.category_combo)
        
        # Название
        self.title_edit = QLineEdit(self.metadata.get("title", ""))
        layout.addRow("Название:", self.title_edit)
        
        # Исполнитель
        self.artist_edit = QLineEdit(self.metadata.get("artist", ""))
        layout.addRow("Исполнитель:", self.artist_edit)
        
        # Альбом
        self.album_edit = QLineEdit(self.metadata.get("album", ""))
        layout.addRow("Альбом:", self.album_edit)
        
        # Теги
        self.tags_edit = QLineEdit(", ".join(self.metadata.get("tags", [])))
        layout.addRow("Теги:", self.tags_edit)
        
        # Рейтинг
        self.rating_spin = QSpinBox()
        self.rating_spin.setRange(0, 5)
        self.rating_spin.setValue(self.metadata.get("rating", 0))
        layout.addRow("Рейтинг:", self.rating_spin)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addRow("", btn_layout)
        
        self.setLayout(layout)
    
    def get_metadata(self):
        """Возвращает обновленные метаданные"""
        return {
            "category": self.category_combo.currentText(),
            "title": self.title_edit.text(),
            "artist": self.artist_edit.text(),
            "album": self.album_edit.text(),
            "tags": [tag.strip() for tag in self.tags_edit.text().split(",") if tag.strip()],
            "rating": self.rating_spin.value(),
            "bookmark": self.metadata.get("bookmark", 0)
        }

class SplitDialog(QtWidgets.QDialog):
    def __init__(self, filename, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Разделить аудиокнигу: {filename}")
        self.filename = filename
        
        layout = QVBoxLayout(self)
        
        # Опции разделения
        form_layout = QFormLayout()
        
        # Метод разделения
        self.split_method = QComboBox()
        self.split_method.addItems(["По времени", "По маркерам", "По тишине"])
        form_layout.addRow("Метод:", self.split_method)
        
        # По времени
        self.time_widget = QWidget()
        time_layout = QHBoxLayout(self.time_widget)
        self.minutes_spin = QSpinBox()
        self.minutes_spin.setRange(1, 120)
        self.minutes_spin.setValue(30)
        time_layout.addWidget(self.minutes_spin)
        time_layout.addWidget(QLabel("минут"))
        form_layout.addRow("Длина части:", self.time_widget)
        
        # По маркерам
        self.markers_widget = QWidget()
        markers_layout = QVBoxLayout(self.markers_widget)
        self.markers_text = QTextEdit()
        self.markers_text.setPlaceholderText("Введите метки времени в формате MM:SS или HH:MM:SS, по одной на строку")
        markers_layout.addWidget(self.markers_text)
        form_layout.addRow("Метки времени:", self.markers_widget)
        self.markers_widget.setVisible(False)
        
        # Базовое имя
        self.base_name = QLineEdit()
        base, _ = os.path.splitext(filename)
        self.base_name.setText(base)
        form_layout.addRow("Базовое имя:", self.base_name)
        
        # Формат имени
        self.name_format = QLineEdit("{base}_part{num}")
        form_layout.addRow("Формат имени:", self.name_format)
        
        layout.addLayout(form_layout)
        
        # Таблица частей
        self.parts_table = QTableWidget(0, 3)
        self.parts_table.setHorizontalHeaderLabels(["Начало", "Конец", "Название"])
        self.parts_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.parts_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.parts_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.parts_table)
        
        # Кнопка предпросмотра
        self.preview_btn = QPushButton("Предпросмотр разделения")
        self.preview_btn.clicked.connect(self.preview_split)
        layout.addWidget(self.preview_btn)
        
        # Кнопки
        btn_layout = QHBoxLayout()
        self.split_btn = QPushButton("Разделить")
        self.split_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton("Отмена")
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.split_btn)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)
        
        # Подключаем изменение метода
        self.split_method.currentIndexChanged.connect(self.on_method_changed)
        
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
    
    def on_method_changed(self, index):
        # Показываем/скрываем соответствующие виджеты
        if index == 0:  # По времени
            self.time_widget.setVisible(True)
            self.markers_widget.setVisible(False)
        elif index == 1:  # По маркерам
            self.time_widget.setVisible(False)
            self.markers_widget.setVisible(True)
        elif index == 2:  # По тишине
            self.time_widget.setVisible(False)
            self.markers_widget.setVisible(False)
    
    def preview_split(self):
        """Предпросмотр разделения"""
        from pydub import AudioSegment
        
        # Очищаем таблицу
        self.parts_table.setRowCount(0)
        
        try:
            # Загружаем аудио
            src = os.path.join(AUDIO_DIR, self.filename)
            audio = AudioSegment.from_file(src)
            total_length = len(audio)
            
            # Получаем точки разделения в зависимости от метода
            splits = []
            
            if self.split_method.currentIndex() == 0:  # По времени
                mins = self.minutes_spin.value()
                ms = mins * 60 * 1000
                splits = list(range(0, total_length, ms))
                if splits[-1] != total_length:
                    splits.append(total_length)
            
            elif self.split_method.currentIndex() == 1:  # По маркерам
                markers_text = self.markers_text.toPlainText().strip()
                if not markers_text:
                    QMessageBox.warning(self, "Ошибка", "Введите метки времени")
                    return
                
                # Парсим маркеры
                splits = [0]  # Начинаем с 0
                for line in markers_text.split("\n"):
                    if not line.strip():
                        continue
                    
                    # Парсим время
                    parts = line.strip().split(":")
                    if len(parts) == 2:  # MM:SS
                        m, s = map(int, parts)
                        ms = (m * 60 + s) * 1000
                    elif len(parts) == 3:  # HH:MM:SS
                        h, m, s = map(int, parts)
                        ms = (h * 3600 + m * 60 + s) * 1000
                    else:
                        continue
                    
                    splits.append(ms)
                
                # Добавляем конец файла
                if splits[-1] != total_length:
                    splits.append(total_length)
            
            elif self.split_method.currentIndex() == 2:  # По тишине
                # Находим участки тишины
                from pydub.silence import detect_silence
                silence_ranges = detect_silence(audio, min_silence_len=1000, silence_thresh=-40)
                
                # Используем середины тишины как точки разделения
                splits = [0]
                for start, end in silence_ranges:
                    mid = (start + end) // 2
                    splits.append(mid)
                
                # Добавляем конец файла
                if splits[-1] != total_length:
                    splits.append(total_length)
            
            # Заполняем таблицу
            base = self.base_name.text()
            name_format = self.name_format.text()
            
            for i in range(len(splits) - 1):
                start = splits[i]
                end = splits[i + 1]
                part_name = name_format.format(base=base, num=i+1)
                
                row = self.parts_table.rowCount()
                self.parts_table.insertRow(row)
                
                self.parts_table.setItem(row, 0, QTableWidgetItem(format_time(start)))
                self.parts_table.setItem(row, 1, QTableWidgetItem(format_time(end)))
                self.parts_table.setItem(row, 2, QTableWidgetItem(part_name))
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Ошибка предпросмотра: {str(e)}")
    
    def get_split_info(self):
        """Возвращает информацию для разделения"""
        parts = []
        for row in range(self.parts_table.rowCount()):
            start_text = self.parts_table.item(row, 0).text()
            end_text = self.parts_table.item(row, 1).text()
            part_name = self.parts_table.item(row, 2).text()
            
            # Парсим время
            def parse_time(time_str):
                parts = time_str.split(":")
                if len(parts) == 2:  # MM:SS
                    m, s = map(int, parts)
                    return (m * 60 + s) * 1000
                elif len(parts) == 3:  # HH:MM:SS
                    h, m, s = map(int, parts)
                    return (h * 3600 + m * 60 + s) * 1000
                return 0
            
            start_ms = parse_time(start_text)
            end_ms = parse_time(end_text)
            
            parts.append((start_ms, end_ms, part_name))
        
        return parts

# --- Главное окно приложения ---
class AudioBotApp(QMainWindow):
    new_audio = QtCore.pyqtSignal(str)
    new_search_results = QtCore.pyqtSignal(object)
    progress_update = QtCore.pyqtSignal(float)
    theme_changed = QtCore.pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Telegram Audio Browser")
        self.resize(1000, 700)
        
        # Плеер
        self.player = QMediaPlayer()
        self.player.stateChanged.connect(self.player_state_changed)
        self.player.positionChanged.connect(self.position_changed)
        self.player.durationChanged.connect(self.duration_changed)
        
        # Текущий проигрываемый файл
        self.current_file = None
        
        # ThreadPool
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Создаем UI
        self.create_ui()
        
        # Сигналы
        self.new_audio.connect(self.reload_tree)
        self.new_search_results.connect(self.show_search_results)
        self.theme_changed.connect(self.apply_theme)
        
        # Загрузка существующих
        self.reload_tree()
        
        # Запуск Telegram-поллинга
        app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
        app.add_handler(MessageHandler(filters.AUDIO | filters.VOICE, self.handle_msg))
        threading.Thread(target=app.run_polling, daemon=True).start()
        
        # Применяем тему по умолчанию
        self.apply_theme("light")
        
        # Таймер для обновления времени
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_time_display)
        self.timer.start(500)

    def create_ui(self):
        # Центральный виджет
        central = QWidget()
        main_layout = QVBoxLayout(central)
        
        # --- Верхняя панель с поиском и кнопками ---
        top_panel = QWidget()
        top_layout = QHBoxLayout(top_panel)
        top_layout.setContentsMargins(5, 5, 5, 5)
        
        # Поиск
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Найти музыку/книгу...")
        self.search_btn = QToolButton()
        self.search_btn.setIcon(QIcon.fromTheme("search", QIcon(QApplication.style().standardIcon(QStyle.SP_FileDialogContentsView))))
        self.search_btn.setToolTip("Искать")
        self.search_btn.clicked.connect(self.on_search)
        self.search_input.returnPressed.connect(self.on_search)
        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        
        # URL
        url_layout = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Ссылка для скачивания...")
        self.url_btn = QToolButton()
        self.url_btn.setIcon(QIcon.fromTheme("download", QIcon(QApplication.style().standardIcon(QStyle.SP_ArrowDown))))
        self.url_btn.setToolTip("Скачать")
        self.url_btn.clicked.connect(self.on_download_url)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(self.url_btn)
        
        # Chat ID
        chat_layout = QHBoxLayout()
        self.chat_id_input = QLineEdit()
        self.chat_id_input.setPlaceholderText("Chat ID для отправки...")
        chat_layout.addWidget(self.chat_id_input)
        
        # Тема
        theme_layout = QHBoxLayout()
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Светлая", "Темная"])
        self.theme_combo.setCurrentIndex(0)
        self.theme_combo.currentIndexChanged.connect(
            lambda idx: self.theme_changed.emit("dark" if idx == 1 else "light"))
        theme_layout.addWidget(QLabel("Тема:"))
        theme_layout.addWidget(self.theme_combo)
        
        # Добавляем все в верхнюю панель
        top_layout.addLayout(search_layout, 2)
        top_layout.addLayout(url_layout, 2)
        top_layout.addLayout(chat_layout, 1)
        top_layout.addLayout(theme_layout)
        
        # --- Основная область с сплиттером ---
        splitter = QSplitter(Qt.Horizontal)
        
        # Левая панель с категориями и файлами
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        
        # Дерево категорий и файлов
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Файл", "Действия"])
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.on_context_menu)
        self.tree.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.tree.setDragEnabled(True)
        self.tree.setAcceptDrops(True)
        self.tree.setDropIndicatorShown(True)
        self.tree.setDragDropMode(QTreeWidget.InternalMove)
        left_layout.addWidget(self.tree)
        
        # Правая панель с вкладками
        right_panel = QTabWidget()
        
        # Вкладка плеера
        player_tab = QWidget()
        player_layout = QVBoxLayout(player_tab)
        
        # Информация о треке
        track_info = QWidget()
        track_layout = QVBoxLayout(track_info)
        self.track_title = QLabel("Нет проигрываемого файла")
        self.track_title.setAlignment(Qt.AlignCenter)
        self.track_title.setFont(QFont('Arial', 12, QFont.Bold))
        self.track_artist = QLabel("")
        self.track_artist.setAlignment(Qt.AlignCenter)
        track_layout.addWidget(self.track_title)
        track_layout.addWidget(self.track_artist)
        
        # Элементы управления плеером
        controls = QWidget()
        controls_layout = QHBoxLayout(controls)
        
        self.play_btn = QToolButton()
        self.play_btn.setIcon(QIcon.fromTheme("media-playback-start", 
                              QIcon(QApplication.style().standardIcon(QStyle.SP_MediaPlay))))
        self.play_btn.setIconSize(QtCore.QSize(32, 32))
        self.play_btn.clicked.connect(self.toggle_playback)
        
        self.stop_btn = QToolButton()
        self.stop_btn.setIcon(QIcon.fromTheme("media-playback-stop", 
                              QIcon(QApplication.style().standardIcon(QStyle.SP_MediaStop))))
        self.stop_btn.setIconSize(QtCore.QSize(32, 32))
        self.stop_btn.clicked.connect(self.stop_playback)
        
        self.prev_btn = QToolButton()
        self.prev_btn.setIcon(QIcon.fromTheme("media-skip-backward", 
                              QIcon(QApplication.style().standardIcon(QStyle.SP_MediaSkipBackward))))
        self.prev_btn.setIconSize(QtCore.QSize(24, 24))
        
        self.next_btn = QToolButton()
        self.next_btn.setIcon(QIcon.fromTheme("media-skip-forward", 
                              QIcon(QApplication.style().standardIcon(QStyle.SP_MediaSkipForward))))
        self.next_btn.setIconSize(QtCore.QSize(24, 24))
        
        self.volume_btn = QToolButton()
        self.volume_btn.setIcon(QIcon.fromTheme("audio-volume-medium", 
                                QIcon(QApplication.style().standardIcon(QStyle.SP_MediaVolume))))
        self.volume_btn.setIconSize(QtCore.QSize(24, 24))
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.valueChanged.connect(self.set_volume)
        
        # Добавляем элементы управления
        controls_layout.addStretch()
        controls_layout.addWidget(self.prev_btn)
        controls_layout.addWidget(self.play_btn)
        controls_layout.addWidget(self.stop_btn)
        controls_layout.addWidget(self.next_btn)
        controls_layout.addStretch()
        controls_layout.addWidget(self.volume_btn)
        controls_layout.addWidget(self.volume_slider)
        
        # Слайдер прогресса и метки времени
        progress_widget = QWidget()
        progress_layout = QHBoxLayout(progress_widget)
        
        self.time_label = QLabel("0:00")
        self.duration_label = QLabel("0:00")
        
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setRange(0, 0)
        self.progress_slider.sliderMoved.connect(self.set_position)
        
        progress_layout.addWidget(self.time_label)
        progress_layout.addWidget(self.progress_slider)
        progress_layout.addWidget(self.duration_label)
        
        # Собираем все в плеер
        player_layout.addWidget(track_info)
        player_layout.addWidget(controls)
        player_layout.addWidget(progress_widget)
        
        # Виджет для визуализации
        viz_widget = QWidget()
        viz_widget.setMinimumHeight(200)
        viz_widget.setStyleSheet("background-color: #e0e0e0;")
        player_layout.addWidget(viz_widget)
        player_layout.addStretch()
        
        # Вкладка с плейлистами
        playlist_tab = QWidget()
        playlist_layout = QVBoxLayout(playlist_tab)
        
        # Добавляем вкладки
        right_panel.addTab(player_tab, "Плеер")
        right_panel.addTab(playlist_tab, "Плейлисты")
        
        # Добавляем панели в сплиттер
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])
        
        # Добавляем все в главный лейаут
        main_layout.addWidget(top_panel)
        main_layout.addWidget(splitter)
        
        # Нижняя панель со статусом
        status_bar = QHBoxLayout()
        self.status_label = QLabel("Готово")
        status_bar.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximumWidth(200)
        self.progress_bar.setVisible(False)
        status_bar.addWidget(self.progress_bar)
        
        main_layout.addLayout(status_bar)
        
        self.setCentralWidget(central)
        
        # Устанавливаем начальную громкость
        self.set_volume(70)

    def apply_theme(self, theme_name):
        """Применяет выбранную тему к приложению"""
        if theme_name not in THEMES:
            theme_name = "light"
        
        theme = THEMES[theme_name]
        
        style = f"""
        QMainWindow, QDialog {{
            background-color: {theme['background']};
            color: {theme['foreground']};
        }}
        QTreeWidget, QTableWidget, QLineEdit, QComboBox, QSpinBox, QTextEdit {{
            background-color: {theme['secondary']};
            color: {theme['foreground']};
            border: 1px solid {theme['accent']};
        }}
        QPushButton, QToolButton {{
            background-color: {theme['accent']};
            color: white;
            border: none;
            padding: 5px;
            border-radius: 2px;
        }}
        QPushButton:hover, QToolButton:hover {{
            background-color: {theme['highlight']};
        }}
        QSlider::groove:horizontal {{
            border: 1px solid {theme['accent']};
            height: 4px;
            background: {theme['secondary']};
            margin: 0px;
            border-radius: 2px;
        }}
        QSlider::handle:horizontal {{
            background: {theme['accent']};
            border: none;
            width: 12px;
            margin: -4px 0;
            border-radius: 6px;
        }}
        QTabWidget::pane {{
            border: 1px solid {theme['accent']};
        }}
        QTabBar::tab {{
            background-color: {theme['secondary']};
            color: {theme['foreground']};
            padding: 6px 12px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }}
        QTabBar::tab:selected {{
            background-color: {theme['accent']};
            color: white;
        }}
        """
        
        self.setStyleSheet(style)

    # --- Поиск ---
    def on_search(self):
        q = self.search_input.text().strip()
        if not q: return
        self.search_btn.setEnabled(False)
        self.status_label.setText(f"Поиск: {q}...")
        self.executor.submit(self._search_task, q)

    def _search_task(self, query):
        try:
            results = search_youtube(query)
        except Exception as e:
            results = []
            print(f"Ошибка поиска: {e}")
        self.new_search_results.emit(results)

    def show_search_results(self, entries):
        self.search_btn.setEnabled(True)
        self.status_label.setText("Готово")
        
        if not entries:
            QMessageBox.information(self, "Нет результатов", "Ничего не найдено.")
            return
        
        dlg = SearchResultsDialog(entries, self.download_from_search, self)
        dlg.exec_()

    def download_from_search(self, video_id, progress_callback=None):
        self.executor.submit(self._download_task, video_id, progress_callback)

    def _download_task(self, video_id, progress_callback=None):
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            self.status_label.setText(f"Скачивание: {url}...")
            
            # Определяем категорию на основе длительности
            results = search_youtube(video_id, 1)
            category = "audiobook" if results and results[0].get('duration', 0) > 600 else "music"
            
            path, fn = download_audio_from_url(url, category, progress_callback)
            if path:
                self.status_label.setText(f"Скачано: {fn}")
                self.new_audio.emit(fn)
            else:
                QtCore.QMetaObject.invokeMethod(
                    self, 
                    lambda: QMessageBox.critical(self, "Ошибка", "Не удалось скачать файл."), 
                    Qt.QueuedConnection
                )
                self.status_label.setText("Ошибка скачивания")
        except Exception as e:
            print(f"Ошибка скачивания: {e}")
            self.status_label.setText(f"Ошибка: {str(e)}")

    # --- Загрузка по URL ---
    def on_download_url(self):
        url = self.url_input.text().strip()
        if not url: return
        
        self.url_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.executor.submit(self._download_url_task, url)

    def _download_url_task(self, url):
        try:
            self.status_label.setText(f"Скачивание: {url}...")
            
            def update_progress(percent):
                self.progress_update.emit(percent)
            
            # Определяем категорию файла
            category = "music"
            if "audiobook" in url.lower() or "book" in url.lower():
                category = "audiobook"
            elif "podcast" in url.lower():
                category = "podcast"
            
            path, fn = download_audio_from_url(url, category, update_progress)
            if path:
                self.status_label.setText(f"Скачано: {fn}")
                self.new_audio.emit(fn)
            else:
                QtCore.QMetaObject.invokeMethod(
                    self, 
                    lambda: QMessageBox.critical(self, "Ошибка", "Не удалось скачать файл."), 
                    Qt.QueuedConnection
                )
                self.status_label.setText("Ошибка скачивания")
        except Exception as e:
            print(f"Ошибка скачивания: {e}")
            self.status_label.setText(f"Ошибка: {str(e)}")
        
        self.progress_bar.setVisible(False)
        QtCore.QMetaObject.invokeMethod(self.url_btn, lambda: self.url_btn.setEnabled(True), Qt.QueuedConnection)

    @pyqtSlot(float)
    def update_progress(self, percent):
        self.progress_bar.setValue(int(percent))

    # --- Дерево файлов и операции ---
    def reload_tree(self):
        self.tree.clear()
        music = QTreeWidgetItem(self.tree, ["Музыка"])
        music.setIcon(0, QIcon.fromTheme("audio-x-generic", 
                    QIcon(QApplication.style().standardIcon(QStyle.SP_MediaVolume))))
        
        books = QTreeWidgetItem(self.tree, ["Аудиокниги"])
        books.setIcon(0, QIcon.fromTheme("x-office-address-book", 
                    QIcon(QApplication.style().standardIcon(QStyle.SP_DirIcon))))
        
        podcasts = QTreeWidgetItem(self.tree, ["Подкасты"])
        podcasts.setIcon(0, QIcon.fromTheme("audio-input-microphone", 
                       QIcon(QApplication.style().standardIcon(QStyle.SP_MediaVolume))))
        
        # Словарь для группировки по папкам
        category_parents = {
            "music": music,
            "audiobook": books,
            "podcast": podcasts
        }
        
        for fn in sorted(os.listdir(AUDIO_DIR)):
            if not fn.lower().endswith((".mp3", ".ogg")): 
                continue
            
            # Получаем или создаем метаданные
            metadata = categories.get(fn, {})
            if isinstance(metadata, str):  # Для совместимости со старым форматом
                metadata = {"category": metadata}
                categories[fn] = metadata
            
            category = metadata.get("category", "music")
            parent = category_parents.get(category, music)
            
            # Создаем элемент дерева
            it = QTreeWidgetItem(parent, [fn])
            
            # Добавляем иконку в зависимости от типа файла
            if fn.lower().endswith(".mp3"):
                it.setIcon(0, QIcon.fromTheme("audio-x-generic"))
            elif fn.lower().endswith(".ogg"):
                it.setIcon(0, QIcon.fromTheme("audio-x-generic"))
            
            # Создаем виджет с кнопками действий
            action_widget = QWidget()
            action_layout = QHBoxLayout(action_widget)
            action_layout.setContentsMargins(2, 2, 2, 2)
            
            # Кнопка воспроизведения
            play_btn = QToolButton()
            play_btn.setIcon(QIcon.fromTheme("media-playback-start", 
                             QIcon(QApplication.style().standardIcon(QStyle.SP_MediaPlay))))
            play_btn.setToolTip("Воспроизвести")
            play_btn.clicked.connect(lambda checked, f=fn: self.play(f))
            
            # Кнопка загрузки
            download_btn = QToolButton()
            download_btn.setIcon(QIcon.fromTheme("document-save", 
                                QIcon(QApplication.style().standardIcon(QStyle.SP_DialogSaveButton))))
            download_btn.setToolTip("Сохранить на диск")
            download_btn.clicked.connect(lambda checked, f=fn: self.download(f))
            
            # Кнопка отправки
            send_btn = QToolButton()
            send_btn.setIcon(QIcon.fromTheme("mail-send", 
                            QIcon(QApplication.style().standardIcon(QStyle.SP_CommandLink))))
            send_btn.setToolTip("Отправить в Telegram")
            send_btn.clicked.connect(lambda checked, f=fn: self.send(f))
            
            # Кнопка метаданных
            meta_btn = QToolButton()
            meta_btn.setIcon(QIcon.fromTheme("document-properties", 
                            QIcon(QApplication.style().standardIcon(QStyle.SP_FileDialogInfoView))))
            meta_btn.setToolTip("Метаданные")
            meta_btn.clicked.connect(lambda checked, f=fn: self.edit_metadata(f))
            
            action_layout.addWidget(play_btn)
            action_layout.addWidget(download_btn)
            action_layout.addWidget(send_btn)
            action_layout.addWidget(meta_btn)
            action_layout.addStretch()
            
            # Устанавливаем виджет в дерево
            self.tree.setItemWidget(it, 1, action_widget)
        
        self.tree.expandAll()

    def on_item_double_clicked(self, item, column):
        """Обработка двойного клика по элементу дерева"""
        if item.parent() is not None and column == 0:
            # Это файл, воспроизводим его
            self.play(item.text(0))

    def play(self, fn):
        """Воспроизведение файла"""
        path = os.path.join(AUDIO_DIR, fn)
        url = QUrl.fromLocalFile(path)
        
        self.current_file = fn
        metadata = categories.get(fn, {})
        if isinstance(metadata, str):  # Для совместимости
            metadata = {"category": metadata}
        
        # Устанавливаем информацию о треке
        title = metadata.get("title", fn)
        artist = metadata.get("artist", "")
        
        self.track_title.setText(title)
        self.track_artist.setText(artist)
        
        # Если есть закладка, восстанавливаем позицию
        bookmark = metadata.get("bookmark", 0)
        
        self.player.setMedia(QMediaContent(url))
        self.player.play()
        
        if bookmark > 0:
            # Спрашиваем, хочет ли пользователь продолжить с закладки
            reply = QMessageBox.question(
                self, 
                "Восстановить позицию", 
                f"Продолжить с позиции {format_time(bookmark * 1000)}?",
                QMessageBox.Yes | QMessageBox.No
            )
            if reply == QMessageBox.Yes:
                # Устанавливаем позицию через небольшую задержку, чтобы плеер успел загрузиться
                QtCore.QTimer.singleShot(500, lambda: self.player.setPosition(bookmark * 1000))

    def download(self, fn):
        """Сохранение файла на диск"""
        src = os.path.join(AUDIO_DIR, fn)
        dst, _ = QFileDialog.getSaveFileName(self, "Сохранить как", fn)
        if dst:
            try:
                shutil.copy(src, dst)
                self.status_label.setText(f"Файл сохранен: {dst}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить файл: {str(e)}")

    def send(self, fn):
        """Отправка файла в Telegram"""
        cid = self.chat_id_input.text().strip()
        if not cid:
            QMessageBox.warning(self, "Ошибка", "Введите Chat ID")
            return
        
        self.status_label.setText(f"Отправка в Telegram: {fn}")
        
        # Отправляем в отдельном потоке
        self.executor.submit(self._send_task, fn, cid)
    
    def _send_task(self, fn, chat_id):
        try:
            bot = Bot(token=TELEGRAM_TOKEN)
            path = os.path.join(AUDIO_DIR, fn)
            
            # Получаем метаданные для подписи
            metadata = categories.get(fn, {})
            if isinstance(metadata, str):
                metadata = {"category": metadata}
            
            title = metadata.get("title", fn)
            artist = metadata.get("artist", "")
            caption = f"{title}"
            if artist:
                caption += f" - {artist}"
            
            with open(path, 'rb') as f:
                if fn.lower().endswith(".ogg"):
                    bot.send_voice(chat_id=chat_id, voice=f, caption=caption)
                else:
                    bot.send_audio(chat_id=chat_id, audio=f, caption=caption)
            
            self.status_label.setText(f"Отправлено: {fn}")
        except Exception as e:
            print(f"Ошибка отправки: {e}")
            self.status_label.setText(f"Ошибка отправки: {str(e)}")
            QtCore.QMetaObject.invokeMethod(
                self, 
                lambda: QMessageBox.critical(self, "Ошибка", f"Не удалось отправить файл: {str(e)}"), 
                Qt.QueuedConnection
            )

    def handle_msg(self, update: Update, context: CallbackContext):
        """Обработка входящих сообщений в Telegram"""
        msg = update.message
        if msg.audio:
            file = msg.audio.get_file()
            fn = msg.audio.file_name or f"{msg.audio.file_id}.mp3"
            
            # Собираем метаданные из сообщения
            metadata = {
                "category": "music",
                "title": msg.audio.title or fn,
                "artist": msg.audio.performer or "",
                "duration": msg.audio.duration
            }
        else:
            file = msg.voice.get_file()
            fn = f"{msg.voice.file_id}.ogg"
            metadata = {
                "category": "podcast",
                "title": fn,
                "duration": msg.voice.duration
            }
        
        path = os.path.join(AUDIO_DIR, fn)
        if not os.path.exists(path):
            file.download(path)
            if fn not in categories:
                categories[fn] = metadata
                save_meta()
            self.new_audio.emit(fn)

    def edit_metadata(self, fn):
        """Редактирование метаданных файла"""
        metadata = categories.get(fn, {})
        if isinstance(metadata, str):  # Для совместимости
            metadata = {"category": metadata}
        
        dlg = MetadataDialog(fn, metadata, self)
        if dlg.exec_() == QDialog.Accepted:
            categories[fn] = dlg.get_metadata()
            save_meta()
            self.reload_tree()
            
            # Если это текущий проигрываемый файл, обновляем информацию
            if self.current_file == fn:
                self.track_title.setText(categories[fn].get("title", fn))
                self.track_artist.setText(categories[fn].get("artist", ""))

    def on_context_menu(self, pos):
        """Контекстное меню для элементов дерева"""
        it = self.tree.itemAt(pos)
        if not it: 
            return
        
        # Если это файл
        if it.parent():
            fn = it.text(0)
            metadata = categories.get(fn, {})
            if isinstance(metadata, str):
                metadata = {"category": metadata}
            category = metadata.get("category", "music")
            
            menu = QMenu()
            
            # Действия для воспроизведения
            play_action = menu.addAction("Воспроизвести")
            play_action.triggered.connect(lambda: self.play(fn))
            
            # Редактирование метаданных
            edit_action = menu.addAction("Редактировать метаданные")
            edit_action.triggered.connect(lambda: self.edit_metadata(fn))
            
            # Действия для категорий
            cat_menu = menu.addMenu("Категория")
            
            music_action = cat_menu.addAction("Музыка")
            music_action.setCheckable(True)
            music_action.setChecked(category == "music")
            music_action.triggered.connect(lambda: self.change_category(fn, "music"))
            
            book_action = cat_menu.addAction("Аудиокнига")
            book_action.setCheckable(True)
            book_action.setChecked(category == "audiobook")
            book_action.triggered.connect(lambda: self.change_category(fn, "audiobook"))
            
            podcast_action = cat_menu.addAction("Подкаст")
            podcast_action.setCheckable(True)
            podcast_action.setChecked(category == "podcast")
            podcast_action.triggered.connect(lambda: self.change_category(fn, "podcast"))
            
            # Если это аудиокнига или подкаст, добавляем опцию разделения
            if category in ["audiobook", "podcast"]:
                menu.addSeparator()
                split_action = menu.addAction("Разделить на части...")
                split_action.triggered.connect(lambda: self.split_dialog(fn))
            
            # Добавляем возможность удаления
            menu.addSeparator()
            delete_action = menu.addAction("Удалить")
            delete_action.triggered.connect(lambda: self.delete_file(fn))
            
            menu.exec_(self.tree.viewport().mapToGlobal(pos))
        
        # Если это категория
        else:
            category = it.text(0).lower()
            if "музыка" in category:
                category = "music"
            elif "книги" in category:
                category = "audiobook"
            elif "подкаст" in category:
                category = "podcast"
            
            menu = QMenu()
            import_action = menu.addAction("Импортировать файл...")
            import_action.triggered.connect(lambda: self.import_file(category))
            
            menu.exec_(self.tree.viewport().mapToGlobal(pos))

    def change_category(self, fn, category):
        """Изменение категории файла"""
        metadata = categories.get(fn, {})
        if isinstance(metadata, str):
            metadata = {"category": category}
        else:
            metadata["category"] = category
        
        categories[fn] = metadata
        save_meta()
        self.reload_tree()

    def delete_file(self, fn):
        """Удаление файла"""
        reply = QMessageBox.question(
            self, 
            "Подтверждение удаления", 
            f"Вы уверены, что хотите удалить файл {fn}?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                path = os.path.join(AUDIO_DIR, fn)
                os.remove(path)
                if fn in categories:
                    del categories[fn]
                    save_meta()
                self.reload_tree()
                self.status_label.setText(f"Файл удален: {fn}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл: {str(e)}")

    def import_file(self, category):
        """Импорт файла с диска"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Импортировать файл", 
            "", 
            "Аудио файлы (*.mp3 *.ogg *.wav *.m4a)"
        )
        
        if file_path:
            try:
                fn = os.path.basename(file_path)
                dst_path = os.path.join(AUDIO_DIR, fn)
                
                # Копируем файл
                shutil.copy(file_path, dst_path)
                
                # Добавляем метаданные
                from mutagen import File
                audio = File(file_path, easy=True)
                
                title = fn
                artist = ""
                album = ""
                
                if audio:
                    if 'title' in audio:
                        title = audio['title'][0]
                    if 'artist' in audio:
                        artist = audio['artist'][0]
                    if 'album' in audio:
                        album = audio['album'][0]
                
                categories[fn] = {
                    "category": category,
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "tags": [],
                    "rating": 0,
                    "bookmark": 0
                }
                save_meta()
                
                self.reload_tree()
                self.status_label.setText(f"Файл импортирован: {fn}")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось импортировать файл: {str(e)}")

    def split_dialog(self, fn):
        """Диалог разделения аудиофайла на части"""
        dlg = SplitDialog(fn, self)
        if dlg.exec_() == QDialog.Accepted:
            self.status_label.setText(f"Разделение файла: {fn}...")
            self.executor.submit(self._split_task, fn, dlg.get_split_info())
    
    def _split_task(self, fn, parts):
        """Задача разделения аудиофайла"""
        try:
            from pydub import AudioSegment
            src = os.path.join(AUDIO_DIR, fn)
            audio = AudioSegment.from_file(src)
            
            # Создаем директорию, если ее нет
            os.makedirs(SPLIT_DIR, exist_ok=True)
            
            # Разделяем файл
            for i, (start_ms, end_ms, part_name) in enumerate(parts):
                part = audio[start_ms:end_ms]
                out = os.path.join(SPLIT_DIR, f"{part_name}.mp3")
                part.export(out, format="mp3")
                
                # Копируем в основную директорию
                dst = os.path.join(AUDIO_DIR, f"{part_name}.mp3")
                shutil.copy(out, dst)
                
                # Создаем метаданные
                metadata = categories.get(fn, {})
                if isinstance(metadata, str):
                    metadata = {"category": metadata}
                
                categories[f"{part_name}.mp3"] = {
                    "category": metadata.get("category", "audiobook"),
                    "title": f"{metadata.get('title', fn)} (Часть {i+1})",
                    "artist": metadata.get("artist", ""),
                    "album": metadata.get("album", ""),
                    "tags": metadata.get("tags", []),
                    "rating": metadata.get("rating", 0),
                    "bookmark": 0
                }
            
            self.status_label.setText(f"Файл разделен на {len(parts)} частей")
            QtCore.QMetaObject.invokeMethod(
                self, 
                lambda: QMessageBox.information(
                    self, 
                    "Разделение завершено", 
                    f"Файл разделен на {len(parts)} частей в директории {SPLIT_DIR}"
                ), 
                Qt.QueuedConnection
            )
            
            # Обновляем дерево файлов
            save_meta()
            self.new_audio.emit("")
        except Exception as e:
            print(f"Ошибка разделения: {e}")
            self.status_label.setText(f"Ошибка разделения: {str(e)}")
            QtCore.QMetaObject.invokeMethod(
                self, 
                lambda: QMessageBox.critical(
                    self, 
                    "Ошибка", 
                    f"Не удалось разделить файл: {str(e)}"
                ), 
                Qt.QueuedConnection
            )

    # --- Функции плеера ---
    def toggle_playback(self):
        """Переключение воспроизведения/паузы"""
        if self.player.state() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def stop_playback(self):
        """Остановка воспроизведения"""
        self.player.stop()

    def set_volume(self, volume):
        """Установка громкости"""
        self.player.setVolume(volume)

    def set_position(self, position):
        """Установка позиции воспроизведения"""
        self.player.setPosition(position)

    def player_state_changed(self, state):
        """Обработка изменения состояния плеера"""
        if state == QMediaPlayer.PlayingState:
            self.play_btn.setIcon(QIcon.fromTheme("media-playback-pause", 
                                 QIcon(QApplication.style().standardIcon(QStyle.SP_MediaPause))))
        else:
            self.play_btn.setIcon(QIcon.fromTheme("media-playback-start", 
                                 QIcon(QApplication.style().standardIcon(QStyle.SP_MediaPlay))))
        
        # Если закончили воспроизведение, сохраняем прогресс
        if state == QMediaPlayer.StoppedState and self.current_file:
            metadata = categories.get(self.current_file, {})
            if isinstance(metadata, str):
                metadata = {"category": metadata}
            
            # Обнуляем закладку при завершении
            metadata["bookmark"] = 0
            categories[self.current_file] = metadata
            save_meta()

    def position_changed(self, position):
        """Обработка изменения позиции воспроизведения"""
        self.progress_slider.setValue(position)
        self.time_label.setText(format_time(position))
        
        # Обновляем закладку каждые 10 секунд
        if self.current_file and position % 10000 < 1000:
            metadata = categories.get(self.current_file, {})
            if isinstance(metadata, str):
                metadata = {"category": metadata}
            
            metadata["bookmark"] = position // 1000
            categories[self.current_file] = metadata
            save_meta()

    def duration_changed(self, duration):
        """Обработка изменения длительности трека"""
        self.progress_slider.setRange(0, duration)
        self.duration_label.setText(format_time(duration))

    def update_time_display(self):
        """Обновление отображения времени воспроизведения"""
        if self.player.state() == QMediaPlayer.PlayingState:
            position = self.player.position()
            self.time_label.setText(format_time(position))
            
    # Добавлен метод для создания и управления плейлистами
    def create_playlist(self):
        """Создание нового плейлиста"""
        name, ok = QInputDialog.getText(self, "Новый плейлист", "Введите название плейлиста:")
        if ok and name:
            playlist_file = os.path.join(PLAYLIST_DIR, f"{name}.json")
            with open(playlist_file, "w", encoding="utf-8") as f:
                json.dump({"name": name, "files": []}, f, ensure_ascii=False, indent=2)
            self.status_label.setText(f"Создан плейлист: {name}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AudioBotApp()
    w.show()
    sys.exit(app.exec_())