import os
import sys
import json
import random
import shutil
import tempfile
from pathlib import Path
from functools import partial
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from pydub import AudioSegment

from PyQt5 import QtCore, QtWidgets, QtGui, QtMultimedia
from PyQt5.QtCore import Qt, QUrl, QSize
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QGraphicsScene, QGraphicsView, QToolButton, QTabWidget,
    QSlider, QAction, QFileDialog, QStyle, QInputDialog, QProgressBar
)
import yt_dlp

# Draggable button for floating menu
class DraggableButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._drag_pos = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(e)

# --- Configuration ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / 'audio_files'
PLAYLIST_DIR = BASE_DIR / 'playlists'
META_FILE = BASE_DIR / 'categories.json'
for d in (AUDIO_DIR, PLAYLIST_DIR):
    d.mkdir(exist_ok=True)

# Load or init metadata
if META_FILE.exists():
    categories = json.loads(META_FILE.read_text(encoding='utf-8'))
else:
    categories = {}

def save_meta():
    META_FILE.write_text(json.dumps(categories, ensure_ascii=False, indent=2), encoding='utf-8')

# --- Dark Theme Colors ---
DARK_BG = "#121212"
DARK_SECONDARY = "#1e1e1e"
ACCENT_COLOR = "#f5a9b8"  # Pink accent similar to image
TEXT_COLOR = "#ffffff"
SECONDARY_TEXT = "#bbbbbb"

# --- Threads for download/search ---
class DownloadThread(QtCore.QThread):
    progress = QtCore.pyqtSignal(float)
    complete = QtCore.pyqtSignal(str)

    def __init__(self, source, category):
        super().__init__()
        self.source = source
        self.category = category

    def run(self):
        outtmpl = str(AUDIO_DIR / '%(title)s.%(ext)s')
        def hook(d):
            if d.get('status') == 'downloading':
                try:
                    p = float(d.get('_percent_str','0%').strip('%'))
                    self.progress.emit(p)
                except:
                    pass

        opts = {
            'format': 'bestaudio',
            'outtmpl': outtmpl,
            'progress_hooks': [hook],
            'postprocessors': [{ 'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3' }],
            'writethumbnail': True
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.source, download=True)
            title = info.get('title') or Path(ydl.prepare_filename(info)).stem
            thumb_file = None
            for ext in ('jpg','png','webp'):
                cand = AUDIO_DIR / f"{title}.{ext}"
                if cand.exists():
                    thumb_file = cand.name
                    break
            fn = Path(ydl.prepare_filename(info)).with_suffix('.mp3').name
            categories[fn] = {'category': self.category, 'title': title, 'thumbnail': thumb_file}
            save_meta()
            self.complete.emit(fn)
        except Exception as e:
            print(f"Download error: {e}")

# --- Main Application ---
class AudioBotApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('AudioBotApp')
        self.resize(800, 600)

        self.executor = ThreadPoolExecutor(4)
        self.playlist = []
        self.current_index = -1
        self.search_thumbnails = []
        self.search_idx = 0
        self.last_query = None

        self._apply_dark_theme()
        self._init_ui()
        self._init_player()
        self.reload_tree()
        self.update_playlist()
        self.show()

    def _apply_dark_theme(self):
        # Set application style sheet for dark theme
        self.setStyleSheet(f"""
            QMainWindow, QWidget, QTabWidget, QTreeWidget {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
            }}
            QTabWidget::pane {{
                border: 1px solid {DARK_SECONDARY};
                background-color: {DARK_BG};
            }}
            QTabBar::tab {{
                background-color: {DARK_SECONDARY};
                color: {SECONDARY_TEXT};
                padding: 8px 16px;
                margin-right: 2px;
                border-radius: 4px 4px 0 0;
            }}
            QTabBar::tab:selected {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
                border-bottom: 2px solid {ACCENT_COLOR};
            }}
            QLineEdit, QProgressBar {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: 1px solid #333;
                border-radius: 4px;
                padding: 5px;
            }}
            QPushButton, QToolButton {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
            }}
            QPushButton:hover, QToolButton:hover {{
                background-color: #333;
            }}
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background-color: {DARK_SECONDARY};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background-color: {ACCENT_COLOR};
                border: none;
                width: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}
            QSlider::add-page:horizontal {{
                background-color: {DARK_SECONDARY};
                border-radius: 3px;
            }}
            QSlider::sub-page:horizontal {{
                background-color: {ACCENT_COLOR};
                border-radius: 3px;
            }}
            QTreeWidget {{
                background-color: {DARK_SECONDARY};
                alternate-background-color: {DARK_BG};
                border: none;
                border-radius: 5px;
                color: {TEXT_COLOR};
            }}
            QTreeWidget::item {{
                padding: 8px;
                border-bottom: 1px solid #333;
            }}
            /* подсветка при наведении */
            QTreeWidget::item:hover {{
                background-color: rgba(255,255,255,0.05);
            }}
            /* сохраняем белый цвет текста при выделении */
            QTreeWidget::item:selected {{
                background-color: #333;
                color: {TEXT_COLOR};
            }}
        """)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # Player panel
        player_panel = QWidget()
        pl = QVBoxLayout(player_panel)
        pl.setSpacing(20)
        pl.setAlignment(Qt.AlignCenter)

        # Cover Art
        self.cover_label = QLabel(alignment=Qt.AlignCenter)
        self.cover_label.setFixedSize(500, 400)
        self.cover_label.setScaledContents(True)
        self.cover_label.setStyleSheet(
            "border: none;"
            "border-radius: 8px;"
            "background-color: transparent;"
        )
        pl.addWidget(self.cover_label, alignment=Qt.AlignCenter)

        # Draggable menu button
        toggle_btn = DraggableButton("≡ Menu")
        toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {SECONDARY_TEXT};
                border: none;
                text-align: left;
                font-size: 14px;
            }}
            QPushButton:hover {{
                color: {TEXT_COLOR};
            }}
        """)
        toggle_btn.clicked.connect(self.toggle_tabs)
        pl.insertWidget(1, toggle_btn, alignment=Qt.AlignLeft)

        # Cover search field and next button
        search_layout = QHBoxLayout()
        self.cover_search = QLineEdit(placeholderText='Search cover (by title)')
        self.cover_search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: none;
                padding: 10px;
                border-radius: 5px;
            }}
        """)
        self.cover_next = QPushButton('Next Cover')
        self.cover_next.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_COLOR};
                color: {DARK_BG};
                font-weight: bold;
                border: none;
                border-radius: 5px;
               	padding: 10px 15px;
            }}
            QPushButton:hover {{
                background-color: {ACCENT_COLOR}cc;
            }}
        """)
        self.cover_next.clicked.connect(self.on_next_cover)
        search_layout.addWidget(self.cover_search)
        search_layout.addWidget(self.cover_next)
        pl.addLayout(search_layout)

        # Track Label
        self.track_label = QLabel('No track selected', alignment=Qt.AlignCenter)
        font = QtGui.QFont('Segoe UI', 20, QtGui.QFont.Bold)
        self.track_label.setFont(font)
        self.track_label.setStyleSheet(f"color: {TEXT_COLOR}; margin-top: 20px;")
        self.track_label.setMinimumHeight(50)
        self.track_label.setWordWrap(True)
        pl.addWidget(self.track_label)

        # Time & Progress
        time_layout = QHBoxLayout()
        self.current_time = QLabel("0:00", alignment=Qt.AlignLeft)
        self.total_time = QLabel("0:00", alignment=Qt.AlignRight)
        self.current_time.setStyleSheet(f"color: {SECONDARY_TEXT};")
        self.total_time.setStyleSheet(f"color: {SECONDARY_TEXT};")
        self.progress_slider = QSlider(Qt.Horizontal)
        self.progress_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background-color: {DARK_SECONDARY};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background-color: {ACCENT_COLOR};
                border: none;
                width...
