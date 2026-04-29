"""USB MIDI input → Qt signals.

Wraps `mido` so the rest of the app can subscribe to Note ON / OFF events
as Qt signals.  `mido` is an optional dependency: if it isn't installed
(or no backend is available), `MidiEngine.is_available()` returns False
and the piano-roll mode in the control window is shown disabled.

Recommended install:  pip install mido python-rtmidi

Note ON / OFF events arrive on the mido callback thread (a worker thread
spun up by python-rtmidi).  Emitting Qt signals across threads is safe;
when the receiving slot lives in the Qt main thread the call is queued
automatically.
"""
from __future__ import annotations
import threading

from PySide6.QtCore import QObject, Signal


try:
    import mido  # type: ignore
    MIDI_AVAILABLE = True
    MIDI_IMPORT_ERROR = ""
except Exception as exc:    # ImportError, but rtmidi load can also raise OSError
    mido = None             # type: ignore
    MIDI_AVAILABLE = False
    MIDI_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


class MidiEngine(QObject):
    """Holds at most one open mido InputPort.

    Public API (all thread-safe; signals are queued):
      * `list_ports()` — refresh the list of available USB MIDI inputs.
      * `open_port(name)` — close any current port and open `name`.
      * `close_port()` — close the current port (no-op if none open).
      * `noteOn(note, velocity)` / `noteOff(note)` — emitted per event.
      * `portChanged(name)` — emitted whenever the open port changes
        ("" = nothing open).
    """

    noteOn       = Signal(int, int)   # (midi note 0..127, velocity 1..127)
    noteOff      = Signal(int)        # (midi note)
    portChanged  = Signal(str)        # currently open port name ("" = closed)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._port = None
        self._port_name = ""

    # ---------- introspection ----------
    @staticmethod
    def is_available() -> bool:
        return MIDI_AVAILABLE

    @staticmethod
    def import_error() -> str:
        return MIDI_IMPORT_ERROR

    def list_ports(self) -> list[str]:
        if not MIDI_AVAILABLE:
            return []
        try:
            return list(mido.get_input_names())
        except Exception:
            return []

    def current_port(self) -> str:
        return self._port_name

    # ---------- open / close ----------
    def open_port(self, name: str) -> tuple[bool, str]:
        if not MIDI_AVAILABLE:
            return False, "mido がインストールされていません"
        self.close_port()
        try:
            port = mido.open_input(name, callback=self._on_msg)
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._port = port
            self._port_name = name
        self.portChanged.emit(name)
        return True, "ok"

    def close_port(self) -> None:
        with self._lock:
            port = self._port
            name = self._port_name
            self._port = None
            self._port_name = ""
        if port is not None:
            try:
                port.close()
            except Exception:
                pass
        if name:
            self.portChanged.emit("")

    # ---------- inbound message routing ----------
    def _on_msg(self, msg) -> None:
        try:
            t = msg.type
        except AttributeError:
            return
        if t == "note_on":
            # Velocity 0 is the running-status form of note-off.
            if getattr(msg, "velocity", 0) > 0:
                self.noteOn.emit(int(msg.note), int(msg.velocity))
            else:
                self.noteOff.emit(int(msg.note))
        elif t == "note_off":
            self.noteOff.emit(int(msg.note))
        # Other message types (CC, pitch bend, program change, ...) are
        # ignored — the piano roll only cares about pitched note events.
