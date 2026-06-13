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

# --- Configuration ---
load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
AUDIO_DIR = BASE_DIR / 'audio_files'
PLAYLIST_DIR = BASE_DIR / 'playlists'
META_FILE = BASE_DIR / 'categories.json'
for d in (AUDIO_DIR, PLAYLIST_DIR): d.mkdir(exist_ok=True)

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
                border: 1px solid {DARK_SECONDARY};
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 5px;
                border-bottom: 1px solid #333;
            }}
            QTreeWidget::item:selected {{
                background-color: #333;
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
        self.cover_label.setFixedSize(500, 400)  # Larger cover art like in image
        self.cover_label.setScaledContents(True)
        self.cover_label.setStyleSheet(
            "border: none;"
            "border-radius: 8px;"
            "background-color: transparent;"
        )
        pl.addWidget(self.cover_label, alignment=Qt.AlignCenter)

        # Track Label (large, styled font with shadow)
        self.track_label = QLabel('No track selected', alignment=Qt.AlignCenter)
        font = QtGui.QFont('Segoe UI', 20, QtGui.QFont.Bold)
        self.track_label.setFont(font)
        self.track_label.setStyleSheet(f"color: {TEXT_COLOR}; margin-top: 20px;")
        self.track_label.setMinimumHeight(50)
        self.track_label.setWordWrap(True)
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

        for b in (btn_prev, btn_play, btn_next):
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

        main_layout.addWidget(player_panel)

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
        toggle_btn = QPushButton("≡ Menu")
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
        main_layout.addWidget(toggle_btn)

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

    def toggle_tabs(self):
        self.tabs.setVisible(not self.tabs.isVisible())

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
            pix = QtGui.QPixmap(str(AUDIO_DIR/thumb))
            self.cover_label.setPixmap(pix)
        else:
            self.cover_label.clear()
        self.status.setText(f'Downloaded: {filename}')
        self.reload_tree()
        self.update_playlist()

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
        self.track_label.setText(track_name)
        
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