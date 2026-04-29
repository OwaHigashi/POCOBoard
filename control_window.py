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
    QApplication, QAbstractScrollArea, QComboBox, QFileDialog, QFrame, QGridLayout,
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider,
    QSpinBox, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

from audio        import AudioEngine
from display_window import DisplayWindow
from media_queue  import MediaQueue, QueueItem
from midi_engine  import MidiEngine
from web_server   import WebBridge


# ---------- style ----------
_QSS = """
QWidget {
    background: #f6f2ec;
    color: #312b26;
    font-family: "Segoe UI Variable Text", "Aptos", "Segoe UI", sans-serif;
    font-size: 14px;
}
QGroupBox {
    background: #fffdfa;
    border: 1px solid #ddd4c8;
    border-radius: 18px;
    margin-top: 14px;
    padding: 14px 12px 10px 12px;
    font-weight: 700;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
    color: #6f645a;
}
QLabel#appTitle {
    color: #342f2a;
    letter-spacing: 1px;
}
QLabel#small, QLabel.small {
    color: #6e665f;
    font-size: 12px;
}
QLabel.url {
    color: #4e5d6a;
    font-family: Consolas, "Cascadia Code", monospace;
    font-size: 14px;
}
QLabel#infoCard {
    background: #fbf8f4;
    border: 1px solid #ded7cd;
    border-radius: 14px;
    padding: 10px 12px;
    color: #433d37;
    font-family: Consolas, "Cascadia Code", monospace;
    font-size: 13px;
}
QWidget#listSurface {
    background: #fbf8f4;
    border-radius: 14px;
}
QWidget#queueRow, QWidget#userRow {
    background: #ffffff;
    border: 1px solid #e3dbd0;
    border-radius: 14px;
}
QLabel#queueMeta, QLabel#userLabel {
    background: transparent;
    color: #342f2a;
}
QLabel#statusDot {
    background: transparent;
    font-size: 18px;
    font-weight: 700;
}
QLabel#statusDot[active="true"] { color: #7da287; }
QLabel#statusDot[active="false"] { color: #b9b1a7; }
QTabWidget::pane {
    border: 1px solid #ddd4c8;
    border-radius: 18px;
    top: -1px;
    background: #fffdfa;
}
QTabBar::tab {
    background: #efe8df;
    color: #675f57;
    padding: 10px 18px;
    border: 1px solid #ddd4c8;
    border-bottom: none;
    border-top-left-radius: 12px;
    border-top-right-radius: 12px;
    margin-right: 4px;
    font-weight: 700;
}
QTabBar::tab:selected {
    background: #fffdfa;
    color: #342f2a;
    border-color: #d3cabf;
}
QTabBar::tab:hover {
    background: #f4eee6;
    color: #48413b;
}
QPushButton {
    background: #f7f2eb;
    color: #342f2a;
    border: 1px solid #d6cdbf;
    border-radius: 12px;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #f1e9de;
    border-color: #cbbfad;
}
QPushButton:pressed {
    background: #ece3d7;
}
QPushButton:disabled {
    background: #f1ede6;
    color: #9a9085;
    border-color: #e1d9ce;
}
QPushButton.primary {
    background: #8aa39a;
    border-color: #789088;
    color: #ffffff;
    font-weight: 800;
}
QPushButton.primary:hover {
    background: #7d978e;
    border-color: #6e877f;
}
QPushButton.fx {
    font-size: 18px;
    font-weight: 800;
    letter-spacing: 1px;
    padding: 16px 12px;
    color: #ffffff;
}
QPushButton.fx:disabled {
    background: #f1ede6;
    color: #b2a99d;
    border-color: #e1d9ce;
}
QPushButton.bomb   { background: #d89a8f; border-color: #cc8a7f; }
QPushButton.clap   { background: #cfb998; border-color: #c1aa87; color: #4b4034; }
QPushButton.hearts { background: #d3a1af; border-color: #c58f9d; }
QPushButton.stars  { background: #d8c69d; border-color: #cab788; color: #4d4331; }
QPushButton.snow   { background: #a7bccb; border-color: #93aaba; color: #ffffff; }
QPushButton.petals { background: #e4b8c8; border-color: #d7a2b5; color: #ffffff; }
QPushButton.aurora { background: #a7c8c1; border-color: #90b5ad; color: #ffffff; }
QPushButton.laser  { background: #b8b3d8; border-color: #a29cc8; color: #ffffff; }
QPushButton.sunset { background: #d8a27f; border-color: #c48b64; color: #ffffff; }
QPushButton.leaves { background: #ca8f62; border-color: #b3744b; color: #ffffff; }
QPushButton.clear {
    background: #c48f80;
    border-color: #b77d6d;
    color: #ffffff;
    font-size: 17px;
    font-weight: 800;
    padding: 14px 12px;
}
QPushButton.clear:hover {
    background: #bb8374;
    border-color: #ac7566;
}
QPushButton.toggleOn {
    background: #8ea79e;
    border-color: #7a9289;
    color: #ffffff;
    font-weight: 700;
}
QPushButton.toggleOff {
    background: #c99a92;
    border-color: #b8867f;
    color: #ffffff;
    font-weight: 700;
}
QPushButton.send {
    background: #93aaa2;
    border-color: #80978f;
    color: #ffffff;
    font-weight: 800;
}
QPushButton.warn {
    background: #cbb390;
    border-color: #b99f78;
    color: #4c4030;
    font-weight: 800;
}
QPushButton.stop {
    background: #cda099;
    border-color: #bc8c84;
    color: #ffffff;
    font-weight: 800;
}
QSlider::groove:horizontal {
    height: 10px;
    background: #e4dbcf;
    border-radius: 5px;
}
QSlider::sub-page:horizontal {
    background: #bfa68a;
    border-radius: 5px;
}
QSlider::handle:horizontal {
    background: #fffdfa;
    width: 20px;
    margin: -6px 0;
    border-radius: 10px;
    border: 2px solid #bfa68a;
}
QComboBox, QSpinBox {
    background: #fffdfa;
    border: 1px solid #d6cdbf;
    padding: 6px 10px;
    border-radius: 10px;
    min-height: 26px;
}
QComboBox QAbstractItemView {
    background: #fffdfa;
    color: #342f2a;
    selection-background-color: #e6ddd2;
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 18px;
    border: none;
    background: transparent;
}
QTextEdit, QPlainTextEdit {
    background: #fffdfa;
    border: 1px solid #ddd4c8;
    border-radius: 14px;
    padding: 10px;
    font-family: "Segoe UI Variable Text", "Segoe UI", sans-serif;
    font-size: 15px;
}
QTextEdit:focus, QComboBox:focus, QSpinBox:focus {
    border-color: #b7aa9a;
}
QScrollArea {
    border: 1px solid #ddd4c8;
    border-radius: 14px;
    background: #fbf8f4;
}
QScrollBar:vertical {
    background: #f5f1ea;
    width: 12px;
    margin: 2px;
}
QScrollBar::handle:vertical {
    background: #d0c5b8;
    border-radius: 5px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #bbaea0;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
"""


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


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
        self.setObjectName("queueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(54)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)

        # Kind pill (color-coded)
        kind_style = {
            "image": ("📷 IMG", "#2a6a88"),
            "video": ("🎬 VID", "#6a3a8a"),
            "audio": ("🎵 MP3", "#3a8a3a"),
        }.get(item.kind, ("📎", "#555"))
        pill = QLabel(kind_style[0])
        pill.setObjectName("queueKindPill")
        pill.setStyleSheet(
            f"background:{kind_style[1]}; color:#fff; "
            "border-radius:8px; padding:5px 8px; "
            "font-weight:700; font-size:11px;"
        )
        pill.setFixedWidth(74)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(pill)

        # File name + sender
        size_kb = max(1, item.size // 1024)
        size_txt = f"{size_kb} KB" if size_kb < 1024 else f"{size_kb/1024:.1f} MB"
        lbl = QLabel(f"{item.filename}   ({size_txt})  —  {item.sender}")
        lbl.setObjectName("queueMeta")
        lbl.setStyleSheet("font-family:'Segoe UI Variable Text'; font-size:13px;")
        lbl.setToolTip(item.path)
        row.addWidget(lbl, 1)

        # Play + delete buttons
        btn_play = QPushButton("▶ 再生")
        btn_play.setFixedWidth(80)
        btn_play.setFixedHeight(30)
        btn_play.setProperty("class", "send")
        _repolish(btn_play)
        btn_play.clicked.connect(lambda: on_play(item))
        row.addWidget(btn_play)

        btn_del = QPushButton("🗑 削除")
        btn_del.setFixedWidth(76)
        btn_del.setFixedHeight(30)
        btn_del.setProperty("class", "stop")
        _repolish(btn_del)
        btn_del.clicked.connect(lambda: on_delete(item))
        row.addWidget(btn_del)


class _UserRow(QWidget):
    """One row in the ユーザー list: LED + name/id + allow/block toggle."""

    def __init__(self, bridge, client_info: dict) -> None:
        super().__init__()
        self._bridge = bridge
        self._client_id = client_info["id"]
        self.setObjectName("userRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedHeight(46)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 6, 12, 6)
        row.setSpacing(10)

        idle_ms = client_info.get("idle_ms", 10_000)
        active = idle_ms < 30_000
        dot = QLabel("●")
        dot.setObjectName("statusDot")
        dot.setProperty("active", active)
        _repolish(dot)
        dot.setFixedWidth(16)
        row.addWidget(dot)

        name = client_info.get("name") or ""
        short = self._client_id[:8]
        label_text = f"{name}  (#{short})" if name else f"#{short}"
        lbl = QLabel(label_text)
        lbl.setToolTip(f"IP: {client_info.get('ip','?')}\nID: {self._client_id}")
        lbl.setObjectName("userLabel")
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
            self.btn.setProperty("class", "toggleOff")
        else:
            self.btn.setText("✓ 許可中")
            self.btn.setProperty("class", "toggleOn")
        _repolish(self.btn)

    def _on_toggled(self, checked: bool) -> None:
        self._bridge.set_blocked(self._client_id, checked)
        self._apply_btn_style()


# ============================================================
#  Main control window
# ============================================================
class ControlWindow(QWidget):

    def __init__(self, bridge: WebBridge, audio: AudioEngine,
                 display: DisplayWindow, queue: MediaQueue,
                 midi: MidiEngine | None = None) -> None:
        super().__init__()
        self.bridge  = bridge
        self.audio   = audio
        self.display = display
        self.queue   = queue
        self.midi    = midi
        self.queue.changed.connect(self._refresh_queue)
        self.display.visualPlaybackStopped.connect(self.queue.clear_playing_visual)
        self.audio.audioPlaybackStopped.connect(self.queue.clear_playing_audio)
        # Mirror display-side piano-mode toggles back into the bridge so the
        # HTTP layer agrees with what the operator sees on screen.
        self.display.pianoModeChanged.connect(self._on_piano_mode_changed)

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
        # Clear the attention color once the operator actually looks at the queue.
        self.tabs.currentChanged.connect(self._on_tab_changed)
        root.addWidget(self.tabs, stretch=1)
        self._refresh_queue()

    def _on_tab_changed(self, idx: int) -> None:
        # Reset the queue-tab highlight color once the operator is on that tab.
        if idx == 0 and hasattr(self, "tabs"):
            # PySide6 doesn't expose the "default" color cleanly, so we clear
            # by passing an invalid QColor which restores the stylesheet default.
            from PySide6.QtGui import QColor
            self.tabs.tabBar().setTabTextColor(0, QColor())

    # ---- top header ----
    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel("🎛  POCOBoard")
        title.setObjectName("appTitle")
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

        self.btnQuit = QPushButton("システム終了")
        self.btnQuit.setProperty("class", "stop")
        self.btnQuit.setMinimumWidth(140)
        self.btnQuit.setMinimumHeight(34)
        self.btnQuit.clicked.connect(self._on_quit_clicked)
        header.addWidget(self.btnQuit)
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
            ("PETALS", "petals"),
            ("AURORA", "aurora"),
            ("LASER",  "laser"),
            ("SUNSET", "sunset"),
            ("LEAVES", "leaves"),
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
        gx.addWidget(stop_btn, 3, 1)
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
        top.addWidget(self.btnStop, 3)

        # ▶ 次へ: pop the top of the queue and play it (useful when push-play
        # is on, or to advance past a paused-in-queue stack).
        self.btnNext = QPushButton("▶ 次へ")
        self.btnNext.setProperty("class", "primary")
        self.btnNext.setMinimumHeight(48)
        _repolish(self.btnNext)
        self.btnNext.clicked.connect(self._on_next)
        top.addWidget(self.btnNext, 2)

        # Auto-play / push-play toggle.  Default = auto-play: new uploads
        # appear on the display immediately (no 再生 click required).
        self.btnAutoplay = QPushButton("自動再生 ON")
        self.btnAutoplay.setCheckable(True)
        self.btnAutoplay.setChecked(True)
        self.btnAutoplay.setMinimumHeight(48)
        self.btnAutoplay.setToolTip(
            "ON  : 受け取った瞬間に表示（キューを素通り）\n"
            "OFF : キューに積んで、再生/次へボタンで送り出す")
        self.btnAutoplay.clicked.connect(self._on_toggle_autoplay)
        top.addWidget(self.btnAutoplay, 2)

        self.btnQueueClear = QPushButton("全削除")
        self.btnQueueClear.setProperty("class", "stop")
        self.btnQueueClear.setMinimumHeight(48)
        self.btnQueueClear.clicked.connect(self._on_queue_clear)
        top.addWidget(self.btnQueueClear, 1)
        layout.addLayout(top)

        # Initial button style for the autoplay toggle.
        self._autoplay = True
        self._apply_autoplay_style()

        # Now-playing indicator (kept compact; highlights what 停止 will kill)
        self.lblNowPlaying = QLabel("再生中: (なし)")
        self.lblNowPlaying.setObjectName("infoCard")
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
        self._queueHost.setObjectName("listSurface")
        self._queueHost.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
                sep.setStyleSheet("color:#d7cec2;")
                row.addWidget(sep)
                continue
            b = QPushButton(label)
            if color:
                b.setStyleSheet(
                    f"background:{color}; color:#ffffff; font-weight:700;"
                    "border:1px solid rgba(70,63,56,0.12);")
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
            "<ue> <shita>  —  <br>"
            "速度 x1〜x5。ピクセル/秒固定 (文字数に関わらず同じ速度で流れます)。")
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

        # Live-tunable image display time (seconds).  Defaults to whatever
        # was loaded from config.ini; 0 = never auto-clear.
        dl.addWidget(QLabel("画像表示時間 (秒):"), 3, 0)
        self.spImageSec = QSpinBox()
        self.spImageSec.setRange(0, 3600)
        self.spImageSec.setSuffix(" 秒")
        self.spImageSec.setSpecialValueText("手動停止まで")
        self.spImageSec.setMinimumHeight(30)
        self.spImageSec.setValue(self.display._image_display_sec)
        self.spImageSec.valueChanged.connect(self._on_image_sec_changed)
        dl.addWidget(self.spImageSec, 3, 1, 1, 2)

        hint = QLabel(
            "※ リモートからアップロードされた画像/動画/音声は自動で背景になります。"
            " 画像は設定秒数で自動消去、動画/音声は config の media_min_play_sec (既定 60 秒)"
            " 以上再生してから自然終了します（短い素材は最低時間までループ）。"
            " 強制停止は「停止」ボタンで。")
        hint.setProperty("class", "small")
        hint.setWordWrap(True)
        dl.addWidget(hint, 4, 0, 1, 3)

        # ---- Piano roll (USB MIDI) ----
        piano_box = self._build_piano_box()
        dl.addWidget(piano_box, 5, 0, 1, 3)

        dl.setRowStretch(6, 1)
        return w

    # ---- piano roll (USB MIDI) controls ----
    def _build_piano_box(self) -> QWidget:
        box = QGroupBox("🎹 ピアノロール (USB MIDI)")
        gl = QGridLayout(box)
        gl.setContentsMargins(10, 10, 10, 10)
        gl.setHorizontalSpacing(10)
        gl.setVerticalSpacing(8)

        # Row 0: ON/OFF toggle + status
        self.btnPianoMode = QPushButton("ピアノロール OFF")
        self.btnPianoMode.setCheckable(True)
        self.btnPianoMode.setMinimumHeight(40)
        self.btnPianoMode.setProperty("class", "toggleOff")
        self.btnPianoMode.clicked.connect(self._on_piano_toggle_clicked)
        gl.addWidget(self.btnPianoMode, 0, 0)

        self.lblPianoStatus = QLabel(self._compose_piano_status())
        self.lblPianoStatus.setObjectName("infoCard")
        self.lblPianoStatus.setWordWrap(True)
        self.lblPianoStatus.setMinimumHeight(40)
        gl.addWidget(self.lblPianoStatus, 0, 1, 1, 2)

        # Row 1: MIDI port combo + refresh
        gl.addWidget(QLabel("MIDI 入力:"), 1, 0)
        self.cbMidiPort = QComboBox()
        self.cbMidiPort.setMinimumHeight(30)
        self.cbMidiPort.activated.connect(self._on_midi_port_picked)
        gl.addWidget(self.cbMidiPort, 1, 1)
        self.btnMidiRefresh = QPushButton("ポート更新")
        self.btnMidiRefresh.setMinimumHeight(30)
        self.btnMidiRefresh.clicked.connect(self._refresh_midi_ports)
        gl.addWidget(self.btnMidiRefresh, 1, 2)

        # Row 2: hint
        if self.midi is None or not MidiEngine.is_available():
            err = MidiEngine.import_error() if self.midi is not None else \
                "MidiEngine が初期化されていません。"
            hint_text = (
                "⚠ MIDI 入力が利用できません: "
                f"{err}\n"
                "POCOBoard は Windows の winmm.dll を直接使うので追加 pip 依存はありません。"
                "それでもこの表示が出る場合はサポートまでご連絡ください。"
            )
        else:
            hint_text = (
                "USB MIDI キーボードを接続し、「ポート更新」→「MIDI 入力:」でポートを選び、"
                "「ピアノロール ON」を押してください。"
                " 演出中は写真／動画は自動的に拒否され、エフェクト (CHEER 等) はピアノロールの上に半透明で重ねて表示されます。"
            )
        self.lblPianoHint = QLabel(hint_text)
        self.lblPianoHint.setProperty("class", "small")
        self.lblPianoHint.setWordWrap(True)
        gl.addWidget(self.lblPianoHint, 2, 0, 1, 3)

        # Initial population.
        self._refresh_midi_ports(emit_log=False)
        return box

    def _compose_piano_status(self) -> str:
        active = self.display.is_piano_mode()
        port = self.midi.current_port() if self.midi is not None else ""
        if active:
            tag = "● 演出中"
        else:
            tag = "○ 停止中"
        port_txt = port if port else "(未接続)"
        return f"{tag}  /  入力: {port_txt}"

    def _refresh_piano_status(self) -> None:
        if hasattr(self, "lblPianoStatus"):
            self.lblPianoStatus.setText(self._compose_piano_status())

    def _refresh_midi_ports(self, emit_log: bool = True) -> None:
        if not hasattr(self, "cbMidiPort"):
            return
        prev = self.cbMidiPort.currentData() or (
            self.midi.current_port() if self.midi is not None else "")
        self.cbMidiPort.blockSignals(True)
        self.cbMidiPort.clear()
        self.cbMidiPort.addItem("(MIDI ポートなし)", "")
        ports: list[str] = []
        if self.midi is not None:
            ports = self.midi.list_ports()
        for name in ports:
            self.cbMidiPort.addItem(name, name)
        # Restore prior selection if still present.
        if prev:
            idx = self.cbMidiPort.findData(prev)
            if idx >= 0:
                self.cbMidiPort.setCurrentIndex(idx)
        self.cbMidiPort.blockSignals(False)
        # If nothing selected and at least one real port, hint at the first.
        if (self.cbMidiPort.currentIndex() <= 0 and ports):
            self.cbMidiPort.setCurrentIndex(1)
        if emit_log:
            self._log_local("ADMIN", f"MIDI ポート一覧を更新 ({len(ports)} 件)")

    def _on_midi_port_picked(self, idx: int) -> None:
        if self.midi is None:
            return
        name = self.cbMidiPort.itemData(idx) or ""
        if not name:
            self.midi.close_port()
            self._refresh_piano_status()
            self._log_local("ADMIN", "MIDI ポート: 切断")
            return
        ok, reason = self.midi.open_port(name)
        if ok:
            self._log_local("ADMIN", f"MIDI ポート接続: {name}")
        else:
            self._log_local("ADMIN", f"MIDI ポート接続失敗: {name} ({reason})")
            # Roll the combo back to "no port" so the operator can retry.
            self.cbMidiPort.setCurrentIndex(0)
        self._refresh_piano_status()

    def _on_piano_toggle_clicked(self, checked: bool) -> None:
        # Forward the new state to the display; pianoModeChanged handler
        # synchronises bridge + button label.
        self.display.set_piano_mode(checked)

    @Slot(bool)
    def _on_piano_mode_changed(self, on: bool) -> None:
        # Keep the bridge in sync so /upload and /status reflect reality.
        self.bridge.set_piano_mode(on)
        if hasattr(self, "btnPianoMode"):
            self.btnPianoMode.blockSignals(True)
            self.btnPianoMode.setChecked(on)
            self.btnPianoMode.blockSignals(False)
            self.btnPianoMode.setText(
                "ピアノロール ON (演出中)" if on else "ピアノロール OFF")
            self.btnPianoMode.setProperty(
                "class", "toggleOn" if on else "toggleOff")
            _repolish(self.btnPianoMode)
        self._refresh_piano_status()
        if on:
            self._log_local("ADMIN", "ピアノロール演出 ON (画像/動画は受付停止)")
        else:
            self._log_local("ADMIN", "ピアノロール演出 OFF")

    def _on_image_sec_changed(self, v: int) -> None:
        self.display.set_image_display_sec(int(v))
        if v == 0:
            self._log_local("ADMIN", "画像表示時間: 手動停止まで")
        else:
            self._log_local("ADMIN", f"画像表示時間: {v}秒")

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
        self._usersHost.setObjectName("listSurface")
        self._usersHost.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
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
            "QTextEdit { background: #fffdfa; color: #433d37; "
            "font-family: Consolas, 'Cascadia Code', monospace; font-size: 13px; "
            "border: 1px solid #ddd4c8; border-radius: 14px; padding: 8px; }"
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
        "BOMB":         "#c57b69",
        "CHEER":        "#a88d55",
        "HEARTS":       "#b9778d",
        "STARS":        "#ae9558",
        "SNOW":         "#6f8fa7",
        "TALK":         "#6d9aa1",
        "MARQUEE":      "#bf8960",
        "MARQUEE/STOP": "#b28787",
        "UPLOAD":       "#73937e",
        "JOIN":         "#7a9f84",
        "NAME":         "#8c7cad",
        "LOCAL":        "#9c87aa",
        "ADMIN":        "#aa7f9a",
        "MY/STOP":      "#b88867",
        "PIANO":        "#4a8fc4",
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

        # Tab-title badge: show pending count so the operator notices
        # a new upload is waiting even when they're looking at another tab.
        # The queue tab is index 0 (see _build_ui).
        self._update_queue_tab_badge(len(items))

    def _update_queue_tab_badge(self, n: int) -> None:
        if not hasattr(self, "tabs"):
            return
        label = "📥 キュー" if n == 0 else f"📥 キュー ({n})"
        self.tabs.setTabText(0, label)
        # When a new item arrives and we're NOT looking at the queue tab,
        # color the tab label to draw the operator's eye. Cleared when the
        # tab is selected (see currentChanged hook).
        prev = getattr(self, "_last_queue_count", 0)
        self._last_queue_count = n
        if n > prev and self.tabs.currentIndex() != 0:
            # QTabBar tab-text color for tab 0 — a bright orange dot of attention
            self.tabs.tabBar().setTabTextColor(0, Qt.GlobalColor.yellow)

    def _dispatch_play(self, item: QueueItem, origin: str = "manual") -> None:
        """Route a taken queue item to display / audio engine.

        `origin` is just a log tag — "auto" when the autoplay handler
        triggered us, "manual" for an explicit 再生/次へ click.
        """
        if not os.path.isfile(item.path):
            self._log_local("ADMIN", f"再生失敗: missing file {item.filename}")
            return
        # Piano-roll mode owns the canvas — image/video are blocked.  Audio
        # still plays because it doesn't compete for screen real estate.
        if self.display.is_piano_mode() and item.kind in ("image", "video"):
            self._log_local(
                "PIANO",
                f"再生スキップ ({item.kind}): ピアノロール演出中  {item.filename}")
            return
        if item.kind == "image":
            ok = self.display.show_image(item.path, f"from {item.sender}", item.cid)
            if not ok:
                self._log_local("ADMIN", f"再生失敗: bad image {item.filename}")
                return
        elif item.kind == "video":
            self.display.play_video(item.path, item.cid)
        elif item.kind == "audio":
            self.audio.play_audio_file(item.path, item.cid)
        self.queue.mark_playing(item)
        tag = "自動再生" if origin == "auto" else "再生"
        self._log_local("ADMIN",
                        f"{tag}: {item.kind} {item.filename} (by {item.sender})")

    def _on_play_item(self, item: QueueItem) -> None:
        taken = self.queue.take(item.id)
        if taken is not None:
            self._dispatch_play(taken, origin="manual")

    def _on_next(self) -> None:
        items = self.queue.items()
        if not items:
            # Nothing to advance to — subtle feedback via button flash.
            self.btnNext.setStyleSheet(
                "background:#ece6dd; color:#93897d; border:1px solid #d8cfc3;"
                "border-radius:12px; font-weight:800; font-size:15px;")
            QTimer.singleShot(400, lambda:
                self.btnNext.setStyleSheet(""))
            return
        self._on_play_item(items[0])

    def _on_toggle_autoplay(self) -> None:
        self._autoplay = self.btnAutoplay.isChecked()
        self._apply_autoplay_style()
        self._log_local("ADMIN",
            f"モード: {'自動再生 ON (受信即表示)' if self._autoplay else 'プッシュ再生 (手動で再生)'}")
        # When switching ON while the queue has items, drain just the
        # first one — matches "receiving triggers display" — rest wait
        # for the next upload or the 次へ button.
        if self._autoplay:
            items = self.queue.items()
            if items and self.queue.playing_visual() is None and \
               self.queue.playing_audio() is None:
                self._on_play_item(items[0])

    def _apply_autoplay_style(self) -> None:
        if self._autoplay:
            self.btnAutoplay.setText("自動再生 ON")
            self.btnAutoplay.setProperty("class", "primary")
        else:
            self.btnAutoplay.setText("プッシュ再生 (手動)")
            self.btnAutoplay.setProperty("class", "warn")
        _repolish(self.btnAutoplay)

    @Slot(str, str, str, str, str)
    def on_media_uploaded(self, cid: str, label: str, ip: str,
                          kind: str, path: str) -> None:
        """Entry point for remote media arrivals (wired in pocoboard.py)."""
        item = self.queue.enqueue(kind, path, label, cid=cid)
        if self._autoplay:
            taken = self.queue.take(item.id)
            if taken is not None:
                self._dispatch_play(taken, origin="auto")

    @Slot(str, str)
    def on_my_stop(self, cid: str, kind: str) -> None:
        """Handle a per-client /my/stop request.

        Stops only items uploaded by this `cid`, both currently playing
        and still queued.  Other users' items are untouched.
        """
        kinds = ("image", "video", "audio") if kind == "all" else (kind,)
        did_any = False
        for k in kinds:
            if k == "image" and self.display._bg_image_owner == cid:
                self.display.clear_image_bg()
                did_any = True
            elif k == "video" and self.display._video_owner == cid:
                self.display.stop_video()
                did_any = True
            elif k == "audio" and self.audio.file_owner() == cid:
                self.audio.stop_audio_file()
                did_any = True
        # Also sweep any still-queued items by this uploader so their stuff
        # doesn't pop up later via 次へ / autoplay.
        dropped = self.queue.remove_by_cid(cid)
        if dropped or did_any:
            self._log_local(
                "MY/STOP",
                f"{cid[:8]}:{kind} → stopped={did_any}, queue_removed={len(dropped)}")

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
    def _on_quit_clicked(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_accept_toggled(self, checked: bool) -> None:
        self.btnAccept.setChecked(checked)
        self.btnAccept.setText("ACCEPT" if checked else "REJECT")
        self.btnAccept.setProperty("class", "toggleOn" if checked else "toggleOff")
        _repolish(self.btnAccept)
        self.bridge.set_accept(checked)

    def _on_volume_changed(self, v: int) -> None:
        self.lblVol.setText(f"{v} / 100")
        self.bridge.set_volume(v)
        self.audio.set_volume(v)

    def _local_fx(self, kind: str) -> None:
        import time
        now_ms = int(time.time() * 1000)
        tag = {"bomb": "BOMB", "clap": "CHEER", "hearts": "HEARTS",
               "stars": "STARS", "snow": "SNOW", "petals": "PETALS",
               "aurora": "AURORA", "laser": "LASER", "sunset": "SUNSET",
               "leaves": "LEAVES"}.get(kind, kind.upper())
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
            self.btnMqSend.setStyleSheet(
                "background:#cda099; border:1px solid #bc8c84; color:#ffffff;"
                "border-radius:12px; font-weight:800;")
            QTimer.singleShot(600, lambda:
                self.btnMqSend.setStyleSheet(""))

    def _local_marquee_stop(self) -> None:
        self.display.stop_marquee()
        self._log_local("MARQUEE/STOP", "STOP")

    def _open_video(self) -> None:
        if self.display.is_piano_mode():
            self._log_local("PIANO", "ローカル動画再生をスキップ (ピアノロール演出中)")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "動画ファイルを選択",
            os.path.expanduser("~"),
            "Video files (*.mp4 *.mkv *.mov *.avi *.webm *.m4v *.wmv);;All files (*)",
        )
        if path:
            self.display.play_video(path)
            self._log_local("LOCAL", f"動画再生: {os.path.basename(path)}")

    def _open_image(self) -> None:
        if self.display.is_piano_mode():
            self._log_local("PIANO", "ローカル画像表示をスキップ (ピアノロール演出中)")
            return
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
