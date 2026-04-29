"""USB MIDI input via the Win32 winmm API → Qt signals.

Calls midiInOpen / midiInStart from `winmm.dll` directly through ctypes,
so this module needs **zero external Python packages** — everything used
ships with stock CPython on Windows.

Design notes:

* The midi callback (registered via `CALLBACK_FUNCTION` flag) runs on a
  Windows multimedia worker thread.  Qt signals are emitted from there;
  receivers in the main thread get them as queued connections
  automatically.  The WINFUNCTYPE wrapper acquires the GIL for us.
* Device IDs and names are enumerated via `midiInGetNumDevs` /
  `midiInGetDevCapsW` (Unicode 'W' variant — Roland / Yamaha drivers
  often emit non-ASCII names).
* The `_cb` reference must be kept alive for the lifetime of `MidiEngine`
  — if Python GCs the ctypes callback object, the next callback into
  freed memory crashes the host.
* This file purposefully does **not** depend on `mido` / `python-rtmidi`.
  `python-rtmidi` is a C++ extension and on Python 3.14 has no
  pre-built Windows wheel yet, so it requires Visual Studio to build
  from source — too fragile a deployment story for a single feature.
"""
from __future__ import annotations
import ctypes
import sys
import threading
from ctypes import (
    POINTER, WINFUNCTYPE, byref, c_size_t, c_uint, c_ulong, c_void_p,
    sizeof, wintypes,
)

from PySide6.QtCore import QObject, Signal


_IS_WINDOWS = sys.platform.startswith("win")

# winmm message types.  We only handle short messages (3 bytes packed
# into dwParam1); SysEx (MIM_LONGDATA) isn't useful for the piano roll.
_MIM_DATA     = 0x3C3
_CALLBACK_FUNCTION = 0x00030000

# midiInOpen result codes that warrant a friendlier error string.
_MMSYSERR_BADDEVICEID = 2
_MMSYSERR_ALLOCATED   = 4
_MMSYSERR_NOMEM       = 7

_MMSYS_ERR_TEXT = {
    _MMSYSERR_BADDEVICEID: "device id 不正",
    _MMSYSERR_ALLOCATED:   "他アプリが占有中",
    _MMSYSERR_NOMEM:       "メモリ不足",
}


class _MIDIINCAPSW(ctypes.Structure):
    """Win32 MIDIINCAPSW — fixed shape used by midiInGetDevCapsW."""
    _fields_ = [
        ("wMid",           wintypes.WORD),
        ("wPid",           wintypes.WORD),
        ("vDriverVersion", c_uint),
        ("szPname",        wintypes.WCHAR * 32),  # MAXPNAMELEN
        ("dwSupport",      c_ulong),
    ]


# void CALLBACK MidiInProc(HMIDIIN, UINT, DWORD_PTR, DWORD_PTR, DWORD_PTR)
_MIDIINPROC = WINFUNCTYPE(
    None, c_void_p, c_uint, c_size_t, c_size_t, c_size_t)


def _bind_winmm():
    """Return the winmm handle with all argtypes/restypes set, or None.

    Setting argtypes/restypes is important on 64-bit Windows so that
    pointer-sized arguments aren't truncated to int.
    """
    if not _IS_WINDOWS:
        return None
    try:
        dll = ctypes.windll.winmm
    except Exception:
        return None
    dll.midiInGetNumDevs.argtypes = []
    dll.midiInGetNumDevs.restype = c_uint
    dll.midiInGetDevCapsW.argtypes = [c_uint, POINTER(_MIDIINCAPSW), c_uint]
    dll.midiInGetDevCapsW.restype = c_uint
    dll.midiInOpen.argtypes = [
        POINTER(c_void_p), c_uint, _MIDIINPROC, c_size_t, c_ulong]
    dll.midiInOpen.restype = c_uint
    dll.midiInStart.argtypes = [c_void_p]
    dll.midiInStart.restype = c_uint
    dll.midiInStop.argtypes = [c_void_p]
    dll.midiInStop.restype = c_uint
    dll.midiInReset.argtypes = [c_void_p]
    dll.midiInReset.restype = c_uint
    dll.midiInClose.argtypes = [c_void_p]
    dll.midiInClose.restype = c_uint
    return dll


_winmm = _bind_winmm()


class MidiEngine(QObject):
    """Win32 winmm-backed MIDI input → Qt signals.

    Public API mirrors the previous mido-based version — no other module
    needs to change when this implementation swaps backends.
    """

    noteOn      = Signal(int, int)   # (midi note 0..127, velocity 1..127)
    noteOff     = Signal(int)        # (midi note)
    portChanged = Signal(str)        # currently open port name ("" = closed)
    # Fired exactly once per port-open the first time a note message
    # arrives.  Lets the control window prove "events are flowing"
    # without spamming the log on every keypress.
    firstNoteSeen = Signal(str)      # (port name)

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._handle = c_void_p()
        self._open = False
        self._port_name = ""
        self._first_note_seen = False
        # Hold the WINFUNCTYPE callback for the engine's lifetime — see
        # module docstring for why this matters.
        self._cb = _MIDIINPROC(self._on_msg)

    # ---------- introspection ----------
    @staticmethod
    def is_available() -> bool:
        return _winmm is not None

    @staticmethod
    def import_error() -> str:
        if not _IS_WINDOWS:
            return "winmm is Windows-only (POCOBoard targets Win11)"
        if _winmm is None:
            return "winmm.dll を ctypes でロードできませんでした"
        return ""

    def list_ports(self) -> list[str]:
        if _winmm is None:
            return []
        try:
            n = int(_winmm.midiInGetNumDevs())
        except Exception:
            return []
        out: list[str] = []
        for i in range(n):
            caps = _MIDIINCAPSW()
            try:
                rc = _winmm.midiInGetDevCapsW(i, byref(caps), sizeof(caps))
            except Exception:
                rc = 1
            if rc == 0:
                name = caps.szPname or f"MIDI Input {i}"
            else:
                name = f"MIDI Input {i}"
            out.append(name)
        return out

    def current_port(self) -> str:
        return self._port_name

    # ---------- open / close ----------
    def open_port(self, name: str) -> tuple[bool, str]:
        if _winmm is None:
            return False, "winmm 利用不可"
        # Resolve name → device index.  Names from midiInGetDevCapsW are
        # stable across enumerations as long as the device stays plugged
        # in, so this round-trip is safe.
        ports = self.list_ports()
        try:
            idx = ports.index(name)
        except ValueError:
            return False, f"ポートが見つかりません: {name}"
        # Close any prior session before we open a new one.
        self.close_port()
        h = c_void_p()
        rc = _winmm.midiInOpen(
            byref(h), c_uint(idx), self._cb, c_size_t(0),
            c_ulong(_CALLBACK_FUNCTION))
        if rc != 0:
            return False, f"midiInOpen 失敗 (mmsys {rc}: {_MMSYS_ERR_TEXT.get(rc, '?')})"
        rc = _winmm.midiInStart(h)
        if rc != 0:
            try: _winmm.midiInClose(h)
            except Exception: pass
            return False, f"midiInStart 失敗 (mmsys {rc})"
        with self._lock:
            self._handle = h
            self._open = True
            self._port_name = name
            self._first_note_seen = False
        self.portChanged.emit(name)
        return True, "ok"

    def close_port(self) -> None:
        with self._lock:
            h = self._handle
            opened = self._open
            name = self._port_name
            self._handle = c_void_p()
            self._open = False
            self._port_name = ""
        if opened and h:
            # Order matters: stop input → reset (drops queued buffers) →
            # close.  Skipping stop or reset can leave the device in a
            # state where the next midiInOpen returns ALLOCATED.
            try: _winmm.midiInStop(h)
            except Exception: pass
            try: _winmm.midiInReset(h)
            except Exception: pass
            try: _winmm.midiInClose(h)
            except Exception: pass
        if name:
            self.portChanged.emit("")

    # ---------- inbound message routing ----------
    def _on_msg(self, hMidiIn, wMsg, dwInstance, dwParam1, dwParam2) -> None:
        # Ignore everything except short messages (Note ON / Note OFF /
        # CC / pitch bend); the piano roll only cares about Note events.
        if wMsg != _MIM_DATA:
            return
        # Short MIDI message packed into dwParam1:
        #   bits 0-7   : status byte
        #   bits 8-15  : data byte 1 (note number)
        #   bits 16-23 : data byte 2 (velocity)
        msg = int(dwParam1) & 0xFFFFFF
        status = msg & 0xFF
        data1  = (msg >> 8) & 0xFF
        data2  = (msg >> 16) & 0xFF
        cmd = status & 0xF0
        if cmd == 0x90:        # Note On (velocity 0 = note off, running status)
            if data2 > 0:
                self._maybe_emit_first_note()
                self.noteOn.emit(data1, data2)
            else:
                self.noteOff.emit(data1)
        elif cmd == 0x80:      # Note Off
            self.noteOff.emit(data1)
        # Channel/CC/pitch-bend events are intentionally ignored.

    def _maybe_emit_first_note(self) -> None:
        # Race-tolerant single-shot: under the lock, swap the flag from
        # False → True and capture the port name.  Then emit the signal
        # outside the lock so a slow slot can't deadlock the callback.
        with self._lock:
            if self._first_note_seen:
                return
            self._first_note_seen = True
            name = self._port_name
        self.firstNoteSeen.emit(name)
