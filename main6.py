import os
import sys
import json
import random
import shutil
import tempfile
from pathlib import Path
from functools import partial
from concurrent.futures import ThreadPoolExecutor
import requests  # For downloading thumbnails

from dotenv import load_dotenv
from pydub import AudioSegment

from PyQt5 import QtCore, QtWidgets, QtGui, QtMultimedia
from PyQt5.QtCore import Qt, QUrl, QSize
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QGraphicsScene, QGraphicsView, QToolButton, QTabWidget,
    QSlider, QAction, QFileDialog, QStyle, QInputDialog, QProgressBar,
    QFrame
)
import yt_dlp

# --- Configuration ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / 'audio_files'
PLAYLIST_DIR = BASE_DIR / 'playlists'
META_FILE = BASE_DIR / 'categories.json'
for d in (AUDIO_DIR, PLAYLIST_DIR): d.mkdir(exist_ok=True)

# Check for required dependencies for thumbnail embedding
try:
    import requests
    from PIL import Image  # Required for thumbnail embedding
except ImportError as e:
    print(f"Warning: Some features might not work properly. Missing dependency: {e}")
    print("Run 'pip install pillow requests' to enable all features.")

# Ensure FFmpeg is available for thumbnail embedding
import subprocess
def check_ffmpeg():
    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except FileNotFoundError:
        print("Warning: FFmpeg not found. Thumbnail embedding may not work.")
        print("Please install FFmpeg and make sure it's in your PATH.")
        return False

HAS_FFMPEG = check_ffmpeg()

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

        # Configure YT-DLP options based on available dependencies
        postprocessors = [{ 'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3' }]
        
        # Add thumbnail embedding if FFmpeg is available
        if HAS_FFMPEG:
            postprocessors.extend([
                { 'key': 'EmbedThumbnail' },  # Embed thumbnail in the audio file
                { 'key': 'FFmpegMetadata' }    # Preserve metadata
            ])
        
        opts = {
            'format': 'bestaudio',
            'outtmpl': outtmpl,
            'progress_hooks': [hook],
            'postprocessors': postprocessors,
            'writethumbnail': True,  # Always download the thumbnail
            'embedthumbnail': HAS_FFMPEG  # Embed thumbnail only if FFmpeg is available
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(self.source, download=True)
            title = info.get('title') or Path(ydl.prepare_filename(info)).stem
            
            # Look for downloaded thumbnail files with various extensions
            thumb_file = None
            # First look for thumbnails with the exact name pattern yt-dlp uses
            file_stem = Path(ydl.prepare_filename(info)).stem
            for ext in ('jpg', 'png', 'webp', 'jpeg'):
                cand = AUDIO_DIR / f"{file_stem}.{ext}"
                if cand.exists():
                    thumb_file = cand.name
                    break
                    
            # If not found, try looking for thumbnail with the title name
            if not thumb_file:
                for ext in ('jpg', 'png', 'webp', 'jpeg'):
                    cand = AUDIO_DIR / f"{title}.{ext}"
                    if cand.exists():
                        thumb_file = cand.name
                        break
                        
            # If still not found, try to extract from the video info
            if not thumb_file and info.get('thumbnail'):
                try:
                    import requests
                    thumb_url = info.get('thumbnail')
                    response = requests.get(thumb_url, timeout=10)
                    if response.status_code == 200:
                        # Save with same name as the audio file but with jpg extension
                        thumb_path = AUDIO_DIR / f"{file_stem}.jpg"
                        with open(thumb_path, 'wb') as f:
                            f.write(response.content)
                        thumb_file = thumb_path.name
                except Exception as e:
                    print(f"Error downloading thumbnail: {e}")
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
        self.resize(500, 700)  # More compact portrait-oriented size

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
        
        # Initialize view state
        self.player_panel.setVisible(True)
        self.tabs.setVisible(False)
        
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
            QTreeWidget::item:selected {{
                background-color: #333;
                color: {TEXT_COLOR};       /* <— обязательно! */
            }}
        """)

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)  # Reduce spacing between elements

        # Player panel
        self.player_panel = QWidget()
        pl = QVBoxLayout(self.player_panel)
        pl.setSpacing(10)  # Tighter spacing for more compact view
        pl.setAlignment(Qt.AlignCenter)

        # Cover Art
        self.cover_label = QLabel(alignment=Qt.AlignCenter)
        self.cover_label.setFixedSize(400, 300)  # Slightly smaller for more compact view
        self.cover_label.setScaledContents(True)
        self.cover_label.setStyleSheet(
            "border: none;"
            "border-radius: 8px;"
            "background-color: transparent;"
        )
        pl.addWidget(self.cover_label, alignment=Qt.AlignCenter)

        # Cover search field and next button - ADDED FROM SECOND EXAMPLE
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

        # Track Label (large, styled font with shadow) with right-click menu
        self.track_label = QLabel('No track selected', alignment=Qt.AlignCenter)
        font = QtGui.QFont('Segoe UI', 20, QtGui.QFont.Bold)
        self.track_label.setFont(font)
        self.track_label.setStyleSheet(f"color: {TEXT_COLOR}; margin-top: 20px;")
        self.track_label.setMinimumHeight(50)
        self.track_label.setWordWrap(True)
        self.track_label.setContextMenuPolicy(Qt.CustomContextMenu)
        self.track_label.customContextMenuRequested.connect(self.show_track_context_menu)
        self.track_label.setMouseTracking(True)
        self.track_label.enterEvent = self.track_label_enter
        self.track_label.leaveEvent = self.track_label_leave
        pl.addWidget(self.track_label)

        # Time labels and Progress slider
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
                width: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
            QSlider::sub-page:horizontal {{
                background-color: {ACCENT_COLOR};
                border-radius: 2px;
            }}
        """)
        
        time_layout.addWidget(self.current_time)
        time_layout.addWidget(self.progress_slider)
        time_layout.addWidget(self.total_time)
        pl.addLayout(time_layout)

        # Controls (centered, large icons with styling)
        ctrl = QHBoxLayout()
        ctrl.setAlignment(Qt.AlignCenter)
        ctrl.setSpacing(30)  # Increased spacing between controls
        icon_size = QSize(48, 48)
        
        # Custom styled control buttons
        btn_prev = QToolButton()
        btn_prev.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipBackward))
        btn_prev.setIconSize(icon_size)
        btn_prev.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                border: none;
            }}
            QToolButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 24px;
            }}
        """)
        btn_prev.clicked.connect(self.prev_track)

        btn_play = QToolButton()
        self.play_btn = btn_play
        btn_play.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        btn_play.setIconSize(QSize(64, 64))  # Larger play button
        btn_play.setStyleSheet(f"""
            QToolButton {{
                background-color: {ACCENT_COLOR};
                border: none;
                border-radius: 32px;
                padding: 10px;
            }}
            QToolButton:hover {{
                background-color: {ACCENT_COLOR}cc;
            }}
        """)
        btn_play.clicked.connect(self.toggle_play)

        btn_next = QToolButton()
        btn_next.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        btn_next.setIconSize(icon_size)
        btn_next.setStyleSheet(f"""
            QToolButton {{
                background-color: transparent;
                border: none;
            }}
            QToolButton:hover {{
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 24px;
            }}
        """)
        btn_next.clicked.connect(self.next_track)

        # Add shuffle button with improved styling
        btn_shuffle = QToolButton()
        btn_shuffle.setText('🔀')
        btn_shuffle.setFixedSize(48, 48)  # Match size with other buttons
        btn_shuffle.setStyleSheet(f"""
            QToolButton {{
                background-color: {DARK_SECONDARY};
                color: {ACCENT_COLOR};
                border: 2px solid {ACCENT_COLOR};
                border-radius: 24px;
                font-size: 22px;
            }}
            QToolButton:hover {{
                background-color: {ACCENT_COLOR};
                color: {DARK_BG};
            }}
        """)
        btn_shuffle.clicked.connect(self.shuffle_tracks)

        for b in (btn_prev, btn_play, btn_next, btn_shuffle):
            b.setCursor(Qt.PointingHandCursor)
            ctrl.addWidget(b)

        pl.addLayout(ctrl)

        # Volume control
        vol_layout = QHBoxLayout()
        vol_layout.setAlignment(Qt.AlignRight)
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet(f"color: {SECONDARY_TEXT}; font-size: 16px;")
        
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(lambda v: self.player.setVolume(v))
        self.volume_slider.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                border: none;
                height: 4px;
                background-color: {DARK_SECONDARY};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background-color: {SECONDARY_TEXT};
                border: none;
                width: 10px;
                margin: -4px 0;
                border-radius: 5px;
            }}
            QSlider::sub-page:horizontal {{
                background-color: {SECONDARY_TEXT};
                border-radius: 2px;
            }}
        """)
        
        vol_layout.addWidget(vol_icon)
        vol_layout.addWidget(self.volume_slider)
        pl.addLayout(vol_layout)

        main_layout.addWidget(self.player_panel)

        # Tabs - hidden initially, will show when menu is toggled
        self.tabs = QTabWidget()
        self.tabs.setVisible(False)
        
        # Library Tab
        lib_tab = QWidget()
        lib_layout = QVBoxLayout(lib_tab)
        
        # Filter bar
        hb = QHBoxLayout()
        self.filter_edit = QLineEdit(placeholderText='Filter library...')
        self.filter_edit.textChanged.connect(self.reload_tree)
        self.filter_edit.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: none;
                padding: 10px;
                border-radius: 5px;
            }}
        """)
        hb.addWidget(self.filter_edit)
        lib_layout.addLayout(hb)
        
        # Library tree
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['File', 'Action'])
        self.tree.setDragDropMode(QTreeWidget.DropOnly)
        self.tree.setAcceptDrops(True)
        self.tree.dragEnterEvent = self.dragEnterEvent
        self.tree.dropEvent = self.dropEvent
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {DARK_SECONDARY};
                alternate-background-color: {DARK_BG};
                border: none;
                border-radius: 5px;
                color: {TEXT_COLOR};
            }}
            QTreeWidget::item {{
                padding: 8px;
            }}
        """)
        lib_layout.addWidget(self.tree)
        self.tabs.addTab(lib_tab, 'Library')

        # Download Tab
        dl_tab = QWidget()
        dl = QVBoxLayout(dl_tab)
        dl_label = QLabel("Download Music")
        dl_label.setFont(QtGui.QFont('Segoe UI', 16, QtGui.QFont.Bold))
        dl_label.setAlignment(Qt.AlignCenter)
        dl.addWidget(dl_label)
        
        dl_input_layout = QHBoxLayout()
        self.download_input = QLineEdit(placeholderText='YouTube/SoundCloud URL or search query')
        self.download_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: none;
                padding: 12px;
                border-radius: 5px;
            }}
        """)
        
        self.download_btn = QPushButton('Download')
        self.download_btn.setFixedHeight(42)
        self.download_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ACCENT_COLOR};
                color: {DARK_BG};
                font-weight: bold;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
            }}
            QPushButton:hover {{
                background-color: {ACCENT_COLOR}cc;
            }}
        """)
        self.download_btn.clicked.connect(self.on_download_input)
        
        dl_input_layout.addWidget(self.download_input)
        dl_input_layout.addWidget(self.download_btn)
        dl.addLayout(dl_input_layout)
        
        self.dl_progress = QProgressBar(visible=False)
        self.dl_progress.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                text-align: center;
                background-color: {DARK_SECONDARY};
                border-radius: 5px;
                height: 20px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_COLOR};
                border-radius: 5px;
            }}
        """)
        dl.addWidget(self.dl_progress)
        
        dl.addStretch(1)
        self.tabs.addTab(dl_tab, 'Download')

        # Waveform Tab
        wf_tab = QWidget()
        wf_layout = QVBoxLayout(wf_tab)
        wf_label = QLabel("Audio Waveform")
        wf_label.setFont(QtGui.QFont('Segoe UI', 16, QtGui.QFont.Bold))
        wf_label.setAlignment(Qt.AlignCenter)
        wf_layout.addWidget(wf_label)
        
        self.wf_view = QGraphicsView()
        self.wf_view.setStyleSheet(f"""
            QGraphicsView {{
                background-color: {DARK_SECONDARY};
                border: none;
                border-radius: 5px;
            }}
        """)
        wf_layout.addWidget(self.wf_view)
        self.tabs.addTab(wf_tab, 'Waveform')

        # Equalizer Tab
        eq_tab = QWidget()
        eq_layout = QVBoxLayout(eq_tab)
        eq_label = QLabel("Equalizer")
        eq_label.setFont(QtGui.QFont('Segoe UI', 16, QtGui.QFont.Bold))
        eq_label.setAlignment(Qt.AlignCenter)
        eq_layout.addWidget(eq_label)
        
        # Styled eq sliders
        slider_style = f"""
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
            QSlider::sub-page:horizontal {{
                background-color: {ACCENT_COLOR};
                border-radius: 3px;
            }}
        """
        
        bass_layout = QVBoxLayout()
        bass_label = QLabel('Bass boost:')
        bass_label.setStyleSheet(f"color: {TEXT_COLOR};")
        self.bass_slider = QSlider(Qt.Horizontal)
        self.bass_slider.setRange(-10, 10)
        self.bass_slider.setStyleSheet(slider_style)
        bass_layout.addWidget(bass_label)
        bass_layout.addWidget(self.bass_slider)
        
        treble_layout = QVBoxLayout()
        treble_label = QLabel('Treble boost:')
        treble_label.setStyleSheet(f"color: {TEXT_COLOR};")
        self.treble_slider = QSlider(Qt.Horizontal)
        self.treble_slider.setRange(-10, 10)
        self.treble_slider.setStyleSheet(slider_style)
        treble_layout.addWidget(treble_label)
        treble_layout.addWidget(self.treble_slider)
        
        eq_layout.addLayout(bass_layout)
        eq_layout.addLayout(treble_layout)
        eq_layout.addStretch(1)
        self.tabs.addTab(eq_tab, 'Equalizer')

        main_layout.addWidget(self.tabs)

        # Toggle tabs button
        self.toggle_btn = QPushButton("≡ Show Library")
        self.toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                font-size: 14px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {ACCENT_COLOR};
                color: {DARK_BG};
            }}
        """)
        self.toggle_btn.clicked.connect(self.toggle_view)
        
        # Create a center-aligned button container
        button_container = QWidget()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.addStretch(1)
        button_layout.addWidget(self.toggle_btn)
        button_layout.addStretch(1)
        
        # Add a separator line
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        separator.setStyleSheet(f"background-color: {DARK_SECONDARY}; max-height: 1px;")
        
        main_layout.addWidget(separator)
        main_layout.addWidget(button_container)

        # Status bar
        status_layout = QHBoxLayout()
        self.status = QLabel('Ready')
        self.status.setStyleSheet(f"color: {SECONDARY_TEXT}; font-size: 12px;")
        self.pbar = QProgressBar(visible=False)
        self.pbar.setStyleSheet(f"""
            QProgressBar {{
                border: none;
                text-align: center;
                background-color: {DARK_SECONDARY};
                border-radius: 3px;
                height: 6px;
            }}
            QProgressBar::chunk {{
                background-color: {ACCENT_COLOR};
                border-radius: 3px;
            }}
        """)
        status_layout.addWidget(self.status)
        status_layout.addWidget(self.pbar)
        main_layout.addLayout(status_layout)

        # Menu
        menu = self.menuBar()
        menu.setStyleSheet(f"""
            QMenuBar {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
            }}
            QMenuBar::item:selected {{
                background-color: {DARK_SECONDARY};
            }}
            QMenu {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
                border: 1px solid {DARK_SECONDARY};
            }}
            QMenu::item:selected {{
                background-color: {DARK_SECONDARY};
            }}
        """)
        file_menu = menu.addMenu('File')
        
        import_act = QAction('Import Audio', self)
        import_act.triggered.connect(self.import_audio)
        file_menu.addAction(import_act)
        
        schedule_menu = menu.addMenu('Schedule')
        act = QAction('Schedule Download', self)
        act.triggered.connect(self.schedule_download)
        schedule_menu.addAction(act)

    def toggle_view(self):
        """Toggle between player view and library/tabs view"""
        if self.tabs.isVisible():
            self.tabs.setVisible(False)
            self.player_panel.setVisible(True)
            self.toggle_btn.setText("≡ Show Library")
        else:
            self.tabs.setVisible(True)
            self.player_panel.setVisible(False)
            self.toggle_btn.setText("≡ Show Player")

    def import_audio(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Audio", "", "Audio Files (*.mp3 *.wav *.ogg *.flac)"
        )
        if file_path:
            self.import_file(file_path)

    def _init_player(self):
        self.player = QtMultimedia.QMediaPlayer()
        self.progress_slider.sliderMoved.connect(lambda pos: self.player.setPosition(pos))
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.stateChanged.connect(self._update_play_icon)
        self.player.setVolume(70)

    def update_position(self, pos):
        self.progress_slider.setValue(pos)
        mins, secs = divmod(pos // 1000, 60)
        self.current_time.setText(f"{mins}:{secs:02d}")

    def update_duration(self, dur):
        self.progress_slider.setRange(0, dur)
        mins, secs = divmod(dur // 1000, 60)
        self.total_time.setText(f"{mins}:{secs:02d}")

    def _update_play_icon(self, state):
        if state == QtMultimedia.QMediaPlayer.PlayingState:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    # --- Cover search functionality (from second example) ---
    def on_next_cover(self):
        """Fetch next cover image from search query."""
        query_text = self.cover_search.text().strip() or self.track_label.text()
        if not query_text or query_text == 'No track selected':
            QMessageBox.warning(self, 'No Query', 'Enter a track title or play a track.')
            return
            
        if not hasattr(self, 'search_thumbnails') or query_text != getattr(self, 'last_query', None):
            # Refresh thumbnails
            try:
                self.status.setText(f'Searching covers for: {query_text}')
                opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(f"ytsearch4:{query_text}", download=False)
                    entries = info.get('entries', [])[:4]
                    self.search_thumbnails = [e.get('thumbnail') for e in entries if e.get('thumbnail')]
                    self.search_idx = 0
                    self.last_query = query_text
            except Exception as e:
                QMessageBox.warning(self, 'Error', f'Error fetching thumbnails: {e}')
                return
                
        if self.search_thumbnails:
            url = self.search_thumbnails[self.search_idx]
            self._fetch_and_show_thumbnail(url)
            self.search_idx = (self.search_idx + 1) % len(self.search_thumbnails)
            self.status.setText(f'Cover {self.search_idx}/{len(self.search_thumbnails)} for: {query_text}')
        else:
            QMessageBox.information(self, 'No Thumbnails', 'No thumbnails found for this query.')

    def _fetch_and_show_thumbnail(self, url):
        """Download and display a thumbnail from a URL."""
        try:
            import requests
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                tmp = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False, dir=str(AUDIO_DIR))
                tmp.write(resp.content)
                tmp.flush()
                pix = QtGui.QPixmap(tmp.name)
                self.cover_label.setPixmap(pix)
                
                # Save metadata thumbnail if a track is playing
                if self.playlist and self.current_index >= 0:
                    fn = self.playlist[self.current_index]
                    thumb_name = Path(tmp.name).name
                    if fn in categories:
                        categories[fn]['thumbnail'] = thumb_name
                        save_meta()
            else:
                QMessageBox.warning(self, 'Download Failed', 'Unable to download cover image.')
        except Exception as e:
            QMessageBox.warning(self, 'Error', f'Error fetching cover: {e}')

    # --- Download handling ---
    def on_download_input(self):
        text = self.download_input.text().strip()
        if not text:
            return
        self.download_btn.setEnabled(False)
        self.dl_progress.setVisible(True)
        source = text if text.startswith('http') else f"ytsearch1:{text}"
        cat = 'music'
        self.dlt = DownloadThread(source, cat)
        self.dlt.progress.connect(lambda p: self.dl_progress.setValue(int(p)))
        self.dlt.complete.connect(self.on_download_complete)
        self.dlt.start()

    def on_download_complete(self, filename):
        self.download_btn.setEnabled(True)
        self.dl_progress.setVisible(False)
        
        meta = categories.get(filename, {})
        thumb = meta.get('thumbnail')
        
        if thumb:
            # Display the downloaded thumbnail
            thumb_path = AUDIO_DIR / thumb
            if thumb_path.exists():
                pix = QtGui.QPixmap(str(thumb_path))
                self.cover_label.setPixmap(pix)
                self.status.setText(f'Downloaded with cover: {filename}')
            else:
                self.cover_label.clear()
                self.status.setText(f'Downloaded: {filename} (no cover found)')
        else:
            # If no thumbnail in metadata, try one more time to find it with the filename pattern
            file_stem = Path(filename).stem
            found_thumb = None
            
            for ext in ('jpg', 'png', 'webp', 'jpeg'):
                thumb_path = AUDIO_DIR / f"{file_stem}.{ext}"
                if thumb_path.exists():
                    found_thumb = thumb_path.name
                    pix = QtGui.QPixmap(str(thumb_path))
                    self.cover_label.setPixmap(pix)
                    
                    # Update metadata with the found thumbnail
                    if filename in categories:
                        categories[filename]['thumbnail'] = found_thumb
                        save_meta()
                        
                    self.status.setText(f'Downloaded with cover: {filename}')
                    break
            
            if not found_thumb:        
                self.cover_label.clear()
                self.cover_label.setStyleSheet(f"""
                    border: none;
                    border-radius: 8px;
                    background-color: {DARK_SECONDARY};
                """)
                self.status.setText(f'Downloaded: {filename}')
        
        # Add the new track to the current playlist
        self.reload_tree()
        self.update_playlist()
        
        # Auto-play the downloaded track
        if filename in self.playlist:
            self.play(filename)

    # --- Drag/drop import ---
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.accept()
    def dropEvent(self, e):
        for url in e.mimeData().urls():
            self.import_file(url.toLocalFile())

    def import_file(self, fp):
        fn = os.path.basename(fp)
        dst = AUDIO_DIR / fn
        if not dst.exists():
            shutil.copy(fp, dst)
        categories[fn] = {'category':'music','title':fn[:-4],'thumbnail':None}
        save_meta()
        self.reload_tree()
        self.update_playlist()

    # --- Library & playback ---
    def reload_tree(self):
        self.tree.clear()
        text = self.filter_edit.text().lower()
        for fn in sorted(os.listdir(AUDIO_DIR)):
            if not fn.endswith('.mp3') or (text and text not in fn.lower()):
                continue
            it = QTreeWidgetItem(self.tree, [fn])
            btn = QToolButton()
            btn.setText('▶')
            btn.setFixedSize(30, 30)
            btn.setStyleSheet(f"""
                QToolButton {{
                    background-color: {ACCENT_COLOR};
                    color: {DARK_BG};
                    border: none;
                    border-radius: 15px;
                    font-weight: bold;
                }}
                QToolButton:hover {{
                    background-color: {ACCENT_COLOR}cc;
                }}
            """)
            btn.clicked.connect(partial(self.play, fn))
            self.tree.setItemWidget(it, 1, btn)

    def update_playlist(self):
        self.playlist = [fn for fn in sorted(os.listdir(AUDIO_DIR)) if fn.endswith('.mp3')]

    def play(self, fn):
        path = str(AUDIO_DIR / fn)
        self.player.setMedia(QtMultimedia.QMediaContent(QUrl.fromLocalFile(path)))
        self.player.play()
        
        # Format track name nicely
        track_name = fn
        if fn in categories:
            track_name = categories[fn].get('title', fn)
        else:
            # Default to filename without extension
            track_name = fn[:-4] if fn.endswith('.mp3') else fn
            
        self.track_label.setText(track_name)
        self.track_label.setStyleSheet(f"color: {TEXT_COLOR}; margin-top: 20px;")  # Reset style
        
        # Set cover art
        meta = categories.get(fn, {})
        thumb = meta.get('thumbnail')
        if thumb:
            pix = QtGui.QPixmap(str(AUDIO_DIR/thumb))
            self.cover_label.setPixmap(pix)
        else:
            # Set default cover if no thumbnail
            self.cover_label.setStyleSheet(f"""
                border: none;
                border-radius: 8px;
                background-color: {DARK_SECONDARY};
            """)
            self.cover_label.clear()
            
        self.current_index = self.playlist.index(fn)
        self.update_playlist()
        self.show_waveform(path)

    # --- Controls ---
    def prev_track(self):
        if self.playlist:
            self.current_index = (self.current_index - 1) % len(self.playlist)
            self.play(self.playlist[self.current_index])
            
    def next_track(self):
        if self.playlist:
            self.current_index = (self.current_index + 1) % len(self.playlist)
            self.play(self.playlist[self.current_index])
            
    def shuffle_tracks(self):
        random.shuffle(self.playlist)
        QMessageBox.information(self, 'Shuffle', 'Playlist shuffled')
        
    def toggle_play(self):
        if self.player.state() == QtMultimedia.QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def schedule_download(self):
        url, ok = QInputDialog.getText(self, 'Schedule Download', 'YouTube URL:')
        if ok and url:
            QMessageBox.information(self, 'Scheduled', f'Download scheduled: {url}')

    # Track label hover effects
    def track_label_enter(self, event):
        """Highlight the track label when mouse enters"""
        if self.current_index >= 0:  # Only highlight if a track is playing
            self.track_label.setStyleSheet(f"color: {ACCENT_COLOR}; margin-top: 20px; text-decoration: underline;")
            self.track_label.setCursor(Qt.PointingHandCursor)
    
    def track_label_leave(self, event):
        """Reset track label style when mouse leaves"""
        self.track_label.setStyleSheet(f"color: {TEXT_COLOR}; margin-top: 20px;")
        self.track_label.setCursor(Qt.ArrowCursor)
    
    def show_track_context_menu(self, pos):
        """Show context menu for renaming track"""
        if self.current_index < 0:  # No track playing
            return
            
        current_file = self.playlist[self.current_index]
        
        # Create menu
        menu = QtWidgets.QMenu()
        menu.setStyleSheet(f"""
            QMenu {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: 1px solid #333;
                border-radius: 4px;
                padding: 5px;
            }}
            QMenu::item {{
                padding: 5px 15px;
                border-radius: 3px;
            }}
            QMenu::item:selected {{
                background-color: {ACCENT_COLOR};
                color: {DARK_BG};
            }}
        """)
        
        rename_action = menu.addAction("Rename track")
        action = menu.exec_(self.track_label.mapToGlobal(pos))
        
        if action == rename_action:
            self.rename_current_track()
    
    def rename_current_track(self):
        """Allow user to rename the current track"""
        if self.current_index < 0:
            return
            
        current_file = self.playlist[self.current_index]
        current_title = categories.get(current_file, {}).get('title', current_file[:-4])
        
        # Create styled dialog
        dialog = QInputDialog(self)
        dialog.setWindowTitle('Rename Track')
        dialog.setLabelText('Enter new track name:')
        dialog.setTextValue(current_title)
        dialog.setStyleSheet(f"""
            QInputDialog {{
                background-color: {DARK_BG};
                color: {TEXT_COLOR};
            }}
            QLabel {{
                color: {TEXT_COLOR};
                font-size: 14px;
            }}
            QLineEdit {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: 1px solid #333;
                border-radius: 4px;
                padding: 8px;
                selection-background-color: {ACCENT_COLOR};
            }}
            QPushButton {{
                background-color: {DARK_SECONDARY};
                color: {TEXT_COLOR};
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                min-width: 80px;
            }}
            QPushButton:hover {{
                background-color: #333;
            }}
            QPushButton:default {{
                background-color: {ACCENT_COLOR};
                color: {DARK_BG};
                font-weight: bold;
            }}
        """)
        
        if dialog.exec_():
            new_title = dialog.textValue()
            if new_title:
                # Update metadata
                if current_file in categories:
                    categories[current_file]['title'] = new_title
                else:
                    categories[current_file] = {
                        'category': 'music',
                        'title': new_title,
                        'thumbnail': None
                    }
                save_meta()
                
                # Update display
                self.track_label.setText(new_title)
                self.status.setText(f'Renamed: {new_title}')
    
    def show_waveform(self, fp):
        try:
            audio = AudioSegment.from_file(fp)
            samples = audio.get_array_of_samples()[::max(1, len(audio)//5000)]
            import matplotlib.pyplot as plt
            plt.figure(figsize=(6,2))
            plt.style.use('dark_background')  # Use dark theme for the plot
            plt.plot(samples, color=ACCENT_COLOR)  # Use accent color for the waveform
            plt.axis('off')  # Remove axes for cleaner look
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            plt.savefig(tmp.name, facecolor=DARK_SECONDARY)
            plt.close()
            pix = QtGui.QPixmap(tmp.name)
            scene = QGraphicsScene()
            scene.addPixmap(pix)
            self.wf_view.setScene(scene)
            self.wf_view.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
        except Exception as e:
            print(f"Waveform error: {e}")

# --- Run ---
if __name__=='__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Consistent style across platforms
    w = AudioBotApp()
    sys.exit(app.exec_())