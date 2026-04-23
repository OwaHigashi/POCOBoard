"""Control window — tabbed operator panel.

Fixed size, fits comfortably on a 1080p monitor.  Top block is always
visible (status, FX, volume, 表示削除); bottom tabs split marquee /
users / display / log so each can use the full available height — the
user list can then scroll through 10+ clients without squeezing the
rest of the UI.
"""
from __future__ import annotations
import os
import socket

from PySide6.QtCore    import Qt, QTimer, Signal, Slot
from PySide6.QtGui     import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractScrollArea, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider,
    QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from audio        import AudioEngine
from display_window import DisplayWindow
from media_queue  import MediaQueue, QueueItem
from web_server   import WebBridge


# ---------- style ----------
_QSS = """
QWidget { background: #13151b; color: #e6e8ee; font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif; font-size: 14px; }
QGroupBox { border: 1px solid #2a2f3a; border-radius: 10px; margin-top: 12px; padding: 12px 10px 8px 10px; font-weight: 700; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #a0b4d0; }
QLabel#small, QLabel.small { color: #93a0b8; font-size: 12px; }
QLabel.url   { color: #8ad0ff; font-family: Consolas, "Cascadia Code", monospace; font-size: 14px; }
QTabWidget::pane { border: 1px solid #2a2f3a; border-radius: 8px; top:-1px; background:#13151b; }
QTabBar::tab { background:#1c2030; color:#b8c2d6; padding: 8px 18px;
               border:1px solid #2a2f3a; border-bottom: none;
               border-top-left-radius:8px; border-top-right-radius:8px;
               margin-right:2px; font-weight:700; }
QTabBar::tab:selected { background:#2a304a; color:#fff; }
QTabBar::tab:hover { background:#252a3c; }
QPushButton { background: #1f2430; color: #eef1f7; border: 1px solid #39404f;
              border-radius: 10px; padding: 8px 12px; font-weight: 600; }
QPushButton:hover { background: #293040; }
QPushButton:pressed { background: #151a24; }
QPushButton.fx { font-size: 18px; font-weight: 800; letter-spacing: 2px;
                 padding: 14px 10px; border: none; color: #fff; }
QPushButton.fx:disabled { background: #2a2f3a; color: #6a7080; }
QPushButton.bomb   { background: qradialgradient(cx:0.3, cy:0.3, radius:1, fx:0.3, fy:0.3,
                      stop:0 #ff8040, stop:0.55 #a02020, stop:1 #300a0a); }
QPushButton.clap   { background: qradialgradient(cx:0.3, cy:0.3, radius:1, fx:0.3, fy:0.3,
                      stop:0 #ffe066, stop:0.55 #cc3a9a, stop:1 #3a1060); }
QPushButton.hearts { background: qradialgradient(cx:0.3, cy:0.3, radius:1, fx:0.3, fy:0.3,
                      stop:0 #ff9acc, stop:0.55 #cc3355, stop:1 #560022); }
QPushButton.stars  { background: qradialgradient(cx:0.3, cy:0.3, radius:1, fx:0.3, fy:0.3,
                      stop:0 #ffffaa, stop:0.5  #e07a10, stop:1 #3a1a00); }
QPushButton.snow   { background: qradialgradient(cx:0.3, cy:0.3, radius:1, fx:0.3, fy:0.3,
                      stop:0 #ffffff, stop:0.6  #88bbee, stop:1 #102038); color: #0a1628; }
QPushButton.clear  { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                      stop:0 #7a1a1a, stop:1 #a05020); color:#fff;
                      font-size:17px; font-weight:800; padding: 14px 10px;
                      border: 1px solid #c06040; }
QPushButton.clear:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                      stop:0 #902020, stop:1 #c06028); }
QPushButton.toggleOn  { background: #1b7f3a; border-color: #2a9a4a; color:#fff; font-weight:700; }
QPushButton.toggleOff { background: #b22525; border-color: #d03a3a; color:#fff; font-weight:700; }
QPushButton.send { background: #1b7f3a; border-color: #2a9a4a; font-weight: 800; }
QPushButton.stop { background: #7f1b1b; border-color: #9a2a2a; font-weight: 800; }
QSlider::groove:horizontal { height: 10px; background: #242a36; border-radius: 5px; }
QSlider::sub-page:horizontal { background: #f0a040; border-radius: 5px; }
QSlider::handle:horizontal { background: #fff; width: 20px; margin: -6px 0;
                             border-radius: 10px; border: 2px solid #3d4556; }
QComboBox { background: #1b1f29; border: 1px solid #39404f; padding: 6px 10px;
            border-radius: 8px; min-height: 26px; }
QComboBox QAbstractItemView { background: #1b1f29; color: #eef1f7;
                              selection-background-color: #2f5fa8; }
QTextEdit, QPlainTextEdit { background: #0c0e14; border: 1px solid #39404f;
                            border-radius: 10px; padding: 10px;
                            font-family: "Segoe UI", sans-serif; font-size: 15px; }
QScrollArea { border: 1px solid #39404f; border-radius: 10px; background:#0c0e14; }
QScrollBar:vertical { background:#0c0e14; width:12px; margin:2px; }
QScrollBar::handle:vertical { background:#39404f; border-radius:4px; min-height:30px; }
QScrollBar::handle:vertical:hover { background:#505a70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""


def _local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


_MARKUP_BUTTONS = [
    ("赤", "r", "#7a1a1a"),
    ("黄", "y", "#7a7a1a"),
    ("緑", "g", "#1a7a1a"),
    ("水", "c", "#1a7a7a"),
    ("青", "b", "#1a1a7a"),
    ("紫", "m", "#7a1a7a"),
    ("橙", "o", "#b55a00"),
    ("桃", "pink", "#a04060"),
    ("白", "w", "#555555"),
    ("|",  None, None),
    ("小", "small", "#2d2d40"),
    ("中", "s2",    "#2d2d40"),
    ("大", "big",   "#2d2d40"),
    ("|",  None, None),
    ("下線", "u",  "#333333"),
    ("強調", "hl", "#222222"),
    ("リセット", "/", "#333333"),
    ("|",  None, None),
    ("上", "ue",    "#204060"),
    ("下", "shita", "#204060"),
]

_COLOR_TAGS = {"r", "g", "b", "y", "c", "m", "w", "o",
               "red", "green", "blue", "yellow", "cyan", "purple",
               "white", "orange", "pink"}
_STANDALONE_TAGS = {"ue", "shita", "top", "bottom", "naka", "middle"}


# ============================================================
#  User list row
# ============================================================
class _QueueRow(QWidget):
    """One queued-media row: icon + metadata + [再生] / [削除] buttons."""

    def __init__(self, item: QueueItem,
                 on_play, on_delete) -> None:
        super().__init__()
        self._item = item
        self.setFixedHeight(42)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(10)

        # Kind pill (color-coded)
        kind_style = {
            "image": ("📷 IMG", "#2a6a88"),
            "video": ("🎬 VID", "#6a3a8a"),
            "audio": ("🎵 MP3", "#3a8a3a"),
        }.get(item.kind, ("📎", "#555"))
        pill = QLabel(kind_style[0])
        pill.setStyleSheet(
            f"background:{kind_style[1]}; color:#fff; "
            "border-radius:6px; padding:4px 8px; "
            "font-weight:700; font-size:11px;"
        )
        pill.setFixedWidth(74)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(pill)

        # File name + sender
        size_kb = max(1, item.size // 1024)
        size_txt = f"{size_kb} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        lbl = QLabel(f"{item.filename}   ({size_txt})  —  {item.sender}")
        lbl.setStyleSheet("font-family:'Segoe UI Variable Text'; font-size:13px;")
        lbl.setToolTip(item.path)
        row.addWidget(lbl, 1)

        # Play + delete buttons
        btn_play = QPushButton("▶ 再生")
        btn_play.setFixedWidth(80)
        btn_play.setFixedHeight(30)
        btn_play.setStyleSheet(
            "background:#1b7f3a; color:#fff; border:1px solid #2a9a4a; "
            "border-radius:6px; font-weight:700;")
        btn_play.clicked.connect(lambda: on_play(item))
        row.addWidget(btn_play)

        btn_del = QPushButton("🗑 削除")
        btn_del.setFixedWidth(76)
        btn_del.setFixedHeight(30)
        btn_del.setStyleSheet(
            "background:#7f1b1b; color:#fff; border:1px solid #9a2a2a; "
            "border-radius:6px; font-weight:700;")
        btn_del.clicked.connect(lambda: on_delete(item))
        row.addWidget(btn_del)


class _UserRow(QWidget):
    """One row in the ユーザー list: LED + name/id + allow/block toggle."""

    def __init__(self, bridge, client_info: dict) -> None:
        super().__init__()
        self._bridge = bridge
        self._client_id = client_info["id"]
        self.setFixedHeight(38)
        self.setStyleSheet("background: transparent;")

        row = QHBoxLayout(self)
        row.setContentsMargins(8, 2, 8, 2)
        row.setSpacing(10)

        idle_ms = client_info.get("idle_ms", 10_000)
        active = idle_ms < 30_000
        dot = QLabel("●")
        dot.setStyleSheet(
            f"color: {'#50e070' if active else '#505560'}; "
            "font-size: 18px; font-weight: bold;"
        )
        dot.setFixedWidth(16)
        row.addWidget(dot)

        name = client_info.get("name") or ""
        short = self._client_id[:8]
        label_text = f"{name}  (#{short})" if name else f"#{short}"
        lbl = QLabel(label_text)
        lbl.setToolTip(f"IP: {client_info.get('ip','?')}\nID: {self._client_id}")
        lbl.setStyleSheet("font-family: 'Segoe UI Variable Text'; font-size: 14px;")
        row.addWidget(lbl, 1)

        self.btn = QPushButton()
        self.btn.setCheckable(True)
        self.btn.setChecked(bool(client_info.get("blocked")))
        self.btn.setFixedWidth(116)
        self.btn.setFixedHeight(30)
        self._apply_btn_style()
        self.btn.clicked.connect(self._on_toggled)
        row.addWidget(self.btn)

    def _apply_btn_style(self) -> None:
        if self.btn.isChecked():
            self.btn.setText("🚫 拒否中")
            self.btn.setStyleSheet(
                "background: #b22525; color: #fff; border: 1px solid #d03a3a; "
                "border-radius: 8px; font-weight: 700;")
        else:
            self.btn.setText("✓ 許可中")
            self.btn.setStyleSheet(
                "background: #1b7f3a; color: #fff; border: 1px solid #2a9a4a; "
                "border-radius: 8px; font-weight: 700;")

    def _on_toggled(self, checked: bool) -> None:
        self._bridge.set_blocked(self._client_id, checked)
        self._apply_btn_style()


# ============================================================
#  Main control window
# ============================================================
class ControlWindow(QWidget):

    def __init__(self, bridge: WebBridge, audio: AudioEngine,
                 display: DisplayWindow, queue: MediaQueue) -> None:
        super().__init__()
        self.bridge  = bridge
        self.audio   = audio
        self.display = display
        self.queue   = queue
        self.queue.changed.connect(self._refresh_queue)

        self.setWindowTitle("POCOBoard — Control")
        self.setStyleSheet(_QSS)
        self.setFixedSize(820, 880)
        self.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint, False)

        self._http_host = "0.0.0.0"
        self._http_port = 8080

        self._build_ui()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()

    # ========== layout ==========
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)

        root.addLayout(self._build_header())
        root.addWidget(self._build_status())
        root.addWidget(self._build_fx())
        root.addWidget(self._build_volume())

        # -------- Tabs --------
        # Queue comes first because during a busy show it's the control the
        # operator touches most often.
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_queue_tab(),   "📥 キュー")
        self.tabs.addTab(self._build_marquee_tab(), "📢 横スクロール")
        self.tabs.addTab(self._build_display_tab(), "🖥 表示")
        self.tabs.addTab(self._build_users_tab(),    "👥 ユーザー")
        self.tabs.addTab(self._build_log_tab(),      "📜 ログ")
        root.addWidget(self.tabs, stretch=1)
        self._refresh_queue()

    # ---- top header ----
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel("🎛  POCOBoard")
        tf = QFont("Segoe UI Variable Display", 20)
        tf.setBold(True)
        title.setFont(tf)
        header.addWidget(title)
        header.addStretch(1)
        self.btnAccept = QPushButton("ACCEPT")
        self.btnAccept.setProperty("class", "toggleOn")
        self.btnAccept.setCheckable(True)
        self.btnAccept.setChecked(True)
        self.btnAccept.setMinimumWidth(120)
        self.btnAccept.setMinimumHeight(34)
        self.btnAccept.clicked.connect(self._on_accept_toggled)
        header.addWidget(self.btnAccept)
        return header

    def _build_status(self) -> QWidget:
        status_box = QGroupBox("ステータス")
        sb = QGridLayout(status_box)
        sb.setColumnStretch(1, 1)
        sb.setContentsMargins(10, 8, 10, 6)
        sb.setVerticalSpacing(4)
        self.lblUrl = QLabel("-")
        self.lblUrl.setProperty("class", "url")
        self.lblUrl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        sb.addWidget(QLabel("リモート URL :"), 0, 0)
        sb.addWidget(self.lblUrl, 0, 1)
        self.lblMq = QLabel("メッセージ 0 件流れ中")
        self.lblMq.setProperty("class", "small")
        sb.addWidget(self.lblMq, 1, 0, 1, 2)
        return status_box

    # ---- FX grid ----
    def _build_fx(self) -> QWidget:
        fx_box = QGroupBox("エフェクト")
        gx = QGridLayout(fx_box)
        gx.setSpacing(8)
        gx.setContentsMargins(10, 8, 10, 8)
        self.fxButtons: dict[str, QPushButton] = {}
        fx_defs = [
            ("BOMB",   "bomb"),
            ("CHEER",  "clap"),
            ("HEARTS", "hearts"),
            ("STARS",  "stars"),
            ("SNOW",   "snow"),
        ]
        for i, (label, kind) in enumerate(fx_defs):
            b = QPushButton(label)
            b.setProperty("class", f"fx {kind}")
            b.setMinimumHeight(62)
            b.clicked.connect(lambda _=False, k=kind: self._local_fx(k))
            gx.addWidget(b, i // 3, i % 3)
            self.fxButtons[kind] = b
        stop_btn = QPushButton("MARQUEE\nSTOP")
        stop_btn.setProperty("class", "stop")
        stop_btn.setMinimumHeight(62)
        stop_btn.clicked.connect(self._local_marquee_stop)
        gx.addWidget(stop_btn, 1, 2)
        return fx_box

    def _build_volume(self) -> QWidget:
        vol_box = QGroupBox("音量")
        vl = QHBoxLayout(vol_box)
        vl.setContentsMargins(10, 8, 10, 8)
        self.volSlider = QSlider(Qt.Orientation.Horizontal)
        self.volSlider.setRange(0, 100)
        self.volSlider.setValue(80)
        self.volSlider.valueChanged.connect(self._on_volume_changed)
        self.lblVol = QLabel("80 / 100")
        self.lblVol.setMinimumWidth(80)
        vl.addWidget(self.volSlider, 1)
        vl.addWidget(self.lblVol)
        return vol_box

    # ---- tab: media queue ----
    def _build_queue_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.setSpacing(8)

        # Top row: 停止 (prominent) + キュー全削除
        top = QHBoxLayout()
        self.btnStop = QPushButton("⛔ 停止 (背景・動画・音声を止める)")
        self.btnStop.setProperty("class", "clear")
        self.btnStop.setMinimumHeight(48)
        self.btnStop.clicked.connect(self._on_stop)
        top.addWidget(self.btnStop, 2)
        self.btnQueueClear = QPushButton("キュー全削除")
        self.btnQueueClear.setProperty("class", "stop")
        self.btnQueueClear.setMinimumHeight(48)
        self.btnQueueClear.clicked.connect(self._on_queue_clear)
        top.addWidget(self.btnQueueClear, 1)
        layout.addLayout(top)

        # Now-playing indicator (kept compact; highlights what 停止 will kill)
        self.lblNowPlaying = QLabel("再生中: (なし)")
        self.lblNowPlaying.setStyleSheet(
            "background:#0c0e14; border:1px solid #39404f; border-radius:8px;"
            "padding:8px 10px; font-family:Consolas,monospace; font-size:13px;"
            "color:#aed6ff;")
        self.lblNowPlaying.setWordWrap(True)
        self.lblNowPlaying.setMinimumHeight(52)
        layout.addWidget(self.lblNowPlaying)

        hdr = QLabel("待機中のメディア（クリックで再生 / 削除）")
        hdr.setProperty("class", "small")
        layout.addWidget(hdr)

        # Scrollable queue list
        self.queueScroll = QScrollArea()
        self.queueScroll.setWidgetResizable(True)
        self._queueHost = QWidget()
        self._queueHost.setStyleSheet("background:#0c0e14;")
        self._queueLayout = QVBoxLayout(self._queueHost)
        self._queueLayout.setContentsMargins(6, 6, 6, 6)
        self._queueLayout.setSpacing(4)
        self._queueLayout.addStretch(1)
        self.queueScroll.setWidget(self._queueHost)
        layout.addWidget(self.queueScroll, stretch=1)
        return w

    # ---- tab: marquee composer ----
    def _build_marquee_tab(self) -> QWidget:
        w = QWidget()
        ml = QVBoxLayout(w)
        ml.setSpacing(8)
        ml.setContentsMargins(10, 12, 10, 10)

        self.mqEdit = QTextEdit()
        self.mqEdit.setPlaceholderText(
            "例: <r>おしらせ</r> <big>19時</big>から開始   "
            "— <ue>...上部固定 <shita>...下部固定")
        self.mqEdit.setFixedHeight(92)
        ml.addWidget(self.mqEdit)

        row = QHBoxLayout()
        row.setSpacing(4)
        for label, tag, color in _MARKUP_BUTTONS:
            if tag is None:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setStyleSheet("color:#39404f;")
                row.addWidget(sep)
                continue
            b = QPushButton(label)
            if color:
                b.setStyleSheet(f"background:{color}; color:#fff; font-weight:700;")
            b.setFixedHeight(30)
            b.setMinimumWidth(36)
            b.clicked.connect(lambda _=False, t=tag: self._insert_tag(t))
            row.addWidget(b)
        row.addStretch(1)
        ml.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("速度:"))
        self.cbSpeed = QComboBox()
        for i in range(1, 6):
            self.cbSpeed.addItem(f"x{i}", i)
        self.cbSpeed.setCurrentIndex(0)
        row2.addWidget(self.cbSpeed)
        row2.addStretch(1)
        self.btnMqSend = QPushButton("流す")
        self.btnMqSend.setProperty("class", "send")
        self.btnMqSend.setMinimumWidth(110)
        self.btnMqSend.setMinimumHeight(34)
        self.btnMqSend.clicked.connect(self._local_marquee_send)
        row2.addWidget(self.btnMqSend)
        self.btnMqStop = QPushButton("停止")
        self.btnMqStop.setProperty("class", "stop")
        self.btnMqStop.setMinimumWidth(100)
        self.btnMqStop.setMinimumHeight(34)
        self.btnMqStop.clicked.connect(self._local_marquee_stop)
        row2.addWidget(self.btnMqStop)
        ml.addLayout(row2)
        ml.addStretch(1)

        hint = QLabel(
            "タグ早見: <r><g><b><y><c><m><o><pink><w>  / "
            "<small><big>  / <u></u>  <hl></hl>  / "
            "<ue> <shita>  —  <br>速度 x1(6秒)〜x5(1.2秒)で画面を横断。")
        hint.setProperty("class", "small")
        hint.setWordWrap(True)
        ml.addWidget(hint)
        return w

    # ---- tab: display window controls ----
    def _build_display_tab(self) -> QWidget:
        w = QWidget()
        dl = QGridLayout(w)
        dl.setContentsMargins(10, 12, 10, 10)
        dl.setHorizontalSpacing(10)
        dl.setVerticalSpacing(10)

        dl.addWidget(QLabel("出力スクリーン:"), 0, 0)
        self.cbScreen = QComboBox()
        self._rebuild_screen_combo()
        self.cbScreen.currentIndexChanged.connect(self._on_screen_changed)
        dl.addWidget(self.cbScreen, 0, 1)
        self.btnFullscreen = QPushButton("フルスクリーン (F11)")
        self.btnFullscreen.setCheckable(True)
        self.btnFullscreen.setMinimumHeight(34)
        self.btnFullscreen.clicked.connect(self._on_fs_toggled)
        dl.addWidget(self.btnFullscreen, 0, 2)

        # Local media pickers — optional, for operator preview.
        dl.addWidget(QLabel("ローカル再生:"), 1, 0)
        self.btnVideoOpen = QPushButton("動画を選ぶ...")
        self.btnVideoOpen.setMinimumHeight(34)
        self.btnVideoOpen.clicked.connect(self._open_video)
        dl.addWidget(self.btnVideoOpen, 1, 1)
        self.btnImageOpen = QPushButton("画像を選ぶ...")
        self.btnImageOpen.setMinimumHeight(34)
        self.btnImageOpen.clicked.connect(self._open_image)
        dl.addWidget(self.btnImageOpen, 1, 2)

        dl.addWidget(QLabel(""), 2, 0)
        self.btnAudioOpen = QPushButton("音声ファイルを選ぶ...")
        self.btnAudioOpen.setMinimumHeight(34)
        self.btnAudioOpen.clicked.connect(self._open_audio)
        dl.addWidget(self.btnAudioOpen, 2, 1, 1, 2)

        hint = QLabel(
            "※ リモートからアップロードされた画像/動画/音声は自動で背景になります。"
            " 停止は「表示削除」ボタンで。")
        hint.setProperty("class", "small")
        hint.setWordWrap(True)
        dl.addWidget(hint, 3, 0, 1, 3)

        dl.setRowStretch(4, 1)
        return w

    # ---- tab: users ----
    def _build_users_tab(self) -> QWidget:
        w = QWidget()
        ul = QVBoxLayout(w)
        ul.setSpacing(8)
        ul.setContentsMargins(10, 12, 10, 10)

        top_row = QHBoxLayout()
        self.btnAllAllow = QPushButton("全員を許可")
        self.btnAllAllow.setProperty("class", "toggleOn")
        self.btnAllAllow.setMinimumHeight(36)
        self.btnAllAllow.clicked.connect(self._all_allow)
        top_row.addWidget(self.btnAllAllow)
        self.btnAllBlock = QPushButton("全員を拒否")
        self.btnAllBlock.setProperty("class", "toggleOff")
        self.btnAllBlock.setMinimumHeight(36)
        self.btnAllBlock.clicked.connect(self._all_block)
        top_row.addWidget(self.btnAllBlock)
        top_row.addStretch(1)
        self.lblUserCount = QLabel("0 人")
        self.lblUserCount.setProperty("class", "small")
        top_row.addWidget(self.lblUserCount)
        self.btnUsersRefresh = QPushButton("更新")
        self.btnUsersRefresh.clicked.connect(self._refresh_user_list)
        top_row.addWidget(self.btnUsersRefresh)
        ul.addLayout(top_row)

        # Scrollable list — expands to fill the whole tab so 10+ clients
        # can be reviewed with a simple drag/scroll.
        self.userScroll = QScrollArea()
        self.userScroll.setWidgetResizable(True)
        self.userScroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._usersHost = QWidget()
        self._usersHost.setStyleSheet("background:#0c0e14;")
        self._usersLayout = QVBoxLayout(self._usersHost)
        self._usersLayout.setContentsMargins(6, 6, 6, 6)
        self._usersLayout.setSpacing(4)
        self._usersLayout.addStretch(1)
        self.userScroll.setWidget(self._usersHost)
        ul.addWidget(self.userScroll, stretch=1)
        return w

    # ---- tab: log ----
    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        ll = QVBoxLayout(w)
        ll.setContentsMargins(10, 12, 10, 10)
        ll.setSpacing(6)
        self.logView = QTextEdit()
        self.logView.setReadOnly(True)
        self.logView.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.logView.setStyleSheet(
            "QTextEdit { background: #06080e; color: #d6dce8; "
            "font-family: Consolas, 'Cascadia Code', monospace; font-size: 13px; "
            "border: 1px solid #39404f; border-radius: 10px; padding: 8px; }"
        )
        ll.addWidget(self.logView, stretch=1)
        row = QHBoxLayout()
        row.addStretch(1)
        self.btnLogClear = QPushButton("ログ消去")
        self.btnLogClear.clicked.connect(self.logView.clear)
        row.addWidget(self.btnLogClear)
        ll.addLayout(row)
        return w

    # ========== public helpers ==========
    def set_http_address(self, host: str, port: int) -> None:
        self._http_host = host
        self._http_port = port
        ip = _local_ip() if host in ("0.0.0.0", "") else host
        self.lblUrl.setText(f"http://{ip}:{port}/   (本機: http://127.0.0.1:{port}/)")

    def set_initial_volume(self, v: int) -> None:
        self.volSlider.setValue(v)

    def set_initial_accept(self, v: bool) -> None:
        self.btnAccept.setChecked(v)
        self._on_accept_toggled(v)

    # ========== status refresh ==========
    def _refresh_status(self) -> None:
        snap = self.bridge.snapshot()
        used = snap["marquee_used"]
        clients = snap["clients"]
        self.lblMq.setText(
            f"メッセージ {used} 件流れ中   /   接続中クライアント: {clients}"
        )

    @Slot(int, int)
    def on_marquee_changed(self, used: int, total: int) -> None:
        self.bridge.set_marquee_status(used, total)

    # ---------------- request log ----------------
    _LOG_COLORS = {
        "BOMB":         "#ff8a4a",
        "CHEER":        "#ffd85a",
        "HEARTS":       "#ff74b0",
        "STARS":        "#ffe06a",
        "SNOW":         "#a8d4ff",
        "TALK":         "#7ee6ea",
        "MARQUEE":      "#ffa85a",
        "MARQUEE/STOP": "#d08a8a",
        "UPLOAD":       "#aaffaa",
        "JOIN":         "#7ee6a2",
        "NAME":         "#c0b4ff",
        "LOCAL":        "#e0b0ff",
        "ADMIN":        "#ffccff",
    }

    @Slot(str, str)
    def on_request_logged(self, kind: str, line: str) -> None:
        color = self._LOG_COLORS.get(kind, "#d6dce8")
        safe = (line.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace("  ", "&nbsp;&nbsp;"))
        self.logView.append(
            f'<span style="color:{color}; font-family:Consolas,monospace;">'
            f'{safe}</span>'
        )
        if self.logView.document().blockCount() > 500:
            c = self.logView.textCursor()
            c.movePosition(c.MoveOperation.Start)
            c.select(c.SelectionType.BlockUnderCursor)
            c.removeSelectedText()
            c.deleteChar()
        sb = self.logView.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _log_local(self, kind: str, details: str = "") -> None:
        import time as _time
        now = _time.strftime("%H:%M:%S")
        line = f"{now}  LOCAL                     {kind:<10s}{details}"
        self.on_request_logged(kind, line)

    # ---------------- user list ----------------
    @Slot()
    def refresh_users(self) -> None:
        self._refresh_user_list()

    def _refresh_user_list(self) -> None:
        while self._usersLayout.count() > 1:
            item = self._usersLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        clients = self.bridge.list_clients()
        self.lblUserCount.setText(f"{len(clients)} 人")
        if not clients:
            empty = QLabel("（まだ誰も接続していません）")
            empty.setProperty("class", "small")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._usersLayout.insertWidget(0, empty)
            return
        for c in clients:
            self._usersLayout.insertWidget(
                self._usersLayout.count() - 1,
                _UserRow(self.bridge, c),
            )

    def _all_allow(self) -> None:
        self.bridge.allow_all()
        self._log_local("ADMIN", "全員許可")

    def _all_block(self) -> None:
        self.bridge.block_all()
        self._log_local("ADMIN", "全員拒否")

    # ---------------- queue ----------------
    def _refresh_queue(self) -> None:
        # Wipe existing rows (keep trailing stretch)
        while self._queueLayout.count() > 1:
            item = self._queueLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        items = self.queue.items()
        if not items:
            empty = QLabel("（キューは空です — ブラウザからアップロードを待機中）")
            empty.setProperty("class", "small")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._queueLayout.insertWidget(0, empty)
        else:
            for it in items:
                self._queueLayout.insertWidget(
                    self._queueLayout.count() - 1,
                    _QueueRow(it, self._on_play_item, self._on_delete_item))

        # Now-playing indicator
        v = self.queue.playing_visual()
        a = self.queue.playing_audio()
        lines = []
        if v is not None:
            icon = "🎬" if v.kind == "video" else "📷"
            lines.append(f"{icon} {v.filename}   ({v.sender})")
        if a is not None:
            lines.append(f"🎵 {a.filename}   ({a.sender})")
        if not lines:
            self.lblNowPlaying.setText("再生中: (なし)")
        else:
            self.lblNowPlaying.setText("再生中:\n" + "\n".join(lines))

    def _on_play_item(self, item: QueueItem) -> None:
        taken = self.queue.take(item.id)
        if taken is None:
            return
        if taken.kind == "image":
            self.display.show_image(taken.path, caption=f"from {taken.sender}")
        elif taken.kind == "video":
            self.display.play_video(taken.path)
        elif taken.kind == "audio":
            self.audio.play_audio_file(taken.path)
        self.queue.mark_playing(taken)
        self._log_local("ADMIN", f"再生: {taken.kind} {taken.filename} (by {taken.sender})")

    def _on_delete_item(self, item: QueueItem) -> None:
        self.queue.remove(item.id)
        self._log_local("ADMIN", f"キューから削除: {item.kind} {item.filename}")

    def _on_stop(self) -> None:
        self.display.clear_display()
        self.audio.stop_audio_file()
        self.queue.stop_all()
        self._log_local("ADMIN", "停止 (背景・動画・音声)")

    def _on_queue_clear(self) -> None:
        n = self.queue.clear()
        if n > 0:
            self._log_local("ADMIN", f"キュー全削除 ({n}件)")

    # ---------------- event handlers ----------------
    def _on_accept_toggled(self, checked: bool) -> None:
        self.btnAccept.setChecked(checked)
        self.btnAccept.setText("ACCEPT" if checked else "REJECT")
        self.btnAccept.setProperty("class", "toggleOn" if checked else "toggleOff")
        self.btnAccept.style().unpolish(self.btnAccept)
        self.btnAccept.style().polish(self.btnAccept)
        self.bridge.set_accept(checked)

    def _on_volume_changed(self, v: int) -> None:
        self.lblVol.setText(f"{v} / 100")
        self.bridge.set_volume(v)
        self.audio.set_volume(v)

    def _local_fx(self, kind: str) -> None:
        import time
        now_ms = int(time.time() * 1000)
        tag = {"bomb": "BOMB", "clap": "CHEER", "hearts": "HEARTS",
               "stars": "STARS", "snow": "SNOW"}.get(kind, kind.upper())
        if not self.bridge.fx_try_acquire(now_ms):
            self._log_local(tag, "  ✖ busy (debounced)")
            return
        self.display.trigger_fx(kind)
        self.audio.play_fx(kind)
        self._log_local(tag)

    def _insert_tag(self, tag: str) -> None:
        te = self.mqEdit
        cur = te.textCursor()
        sel = cur.selectedText()
        if tag == "/":
            cur.insertText("</>")
            te.setTextCursor(cur)
            te.setFocus()
            return
        if tag in _STANDALONE_TAGS:
            text = te.toPlainText()
            te.setPlainText(f"<{tag}>{text}")
            cur = te.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            te.setTextCursor(cur)
            te.setFocus()
            return
        close = "</>" if tag in _COLOR_TAGS else f"</{tag}>"
        if sel:
            cur.insertText(f"<{tag}>{sel}{close}")
        else:
            cur.insertText(f"<{tag}>{close}")
            pos = cur.position() - len(close)
            cur.setPosition(pos)
            te.setTextCursor(cur)
        te.setFocus()

    def _local_marquee_send(self) -> None:
        text = self.mqEdit.toPlainText().strip()
        if not text:
            return
        speed = int(self.cbSpeed.currentData() or 1)
        res = self.display.add_marquee(text, speed)
        preview = text if len(text) <= 60 else text[:57] + "..."
        if res == "OK":
            self._log_local("MARQUEE", f"x{speed}  {preview}")
        else:
            self._log_local("MARQUEE", f"x{speed}  ✖ {res}  {preview}")
            self.btnMqSend.setStyleSheet("background:#7f1b1b; border-color:#9a2a2a;")
            QTimer.singleShot(600, lambda:
                self.btnMqSend.setStyleSheet(""))

    def _local_marquee_stop(self) -> None:
        self.display.stop_marquee()
        self._log_local("MARQUEE/STOP", "STOP")

    def _open_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "動画ファイルを選択",
            os.path.expanduser("~"),
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv);;All files (*)",
        )
        if path:
            self.display.play_video(path)
            self._log_local("LOCAL", f"動画再生: {os.path.basename(path)}")

    def _open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "画像ファイルを選択",
            os.path.expanduser("~"),
            "Images (*.jpg *.jpeg *.png *.webp *.gif *.bmp);;All files (*)",
        )
        if path:
            self.display.show_image(path, caption=f"from LOCAL")
            self._log_local("LOCAL", f"画像表示: {os.path.basename(path)}")

    def _open_audio(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "音声ファイルを選択",
            os.path.expanduser("~"),
            "Audio (*.mp3 *.wav *.m4a *.aac *.ogg *.flac);;All files (*)",
        )
        if path:
            self.audio.play_audio_file(path)
            self._log_local("LOCAL", f"音声再生: {os.path.basename(path)}")

    def _rebuild_screen_combo(self) -> None:
        self.cbScreen.clear()
        screens = QGuiApplication.screens()
        for i, s in enumerate(screens):
            geom = s.geometry()
            name = s.name() or f"Screen {i}"
            self.cbScreen.addItem(
                f"[{i}] {name}  {geom.width()}x{geom.height()}", i)

    def set_selected_screen(self, idx: int) -> None:
        n = self.cbScreen.count()
        if 0 <= idx < n:
            self.cbScreen.setCurrentIndex(idx)

    def _on_screen_changed(self, idx: int) -> None:
        screen_idx = int(self.cbScreen.itemData(idx) or 0)
        was_full = self.display.isFullScreen()
        self.display.place_on_screen(
            screen_idx, fullscreen=was_full, fallback_size=(1600, 900),
        )

    def _on_fs_toggled(self, checked: bool) -> None:
        if checked and not self.display.isFullScreen():
            self.display.showFullScreen()
        elif not checked and self.display.isFullScreen():
            self.display.showNormal()
        self.btnFullscreen.setText(
            "全画面解除 (F11)" if self.display.isFullScreen() else "フルスクリーン (F11)"
        )
