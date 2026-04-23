"""Low-latency audio engine — FX sounds + multi-speaker TALK mixer.

Two QAudioSink instances:

  * `fx_sink`   : 44.1 kHz mono Int16 — short one-shot buffers (bomb/cheer/...)
  * `talk_sink` : 16 kHz mono Int16 — persistent push-mode sink fed by a
                  per-client mixer.

TALK mixing
-----------
Multiple browsers can hold the TALK button at the same time.  Each
client's incoming PCM is enqueued in its own byte buffer.  A 20 ms pump
timer drains 320 samples from every client buffer, sums them per sample,
saturates to Int16, and writes the mixed slice to the sink.  Silence
chunks are written when all clients are idle to keep the sink "warm" —
avoids the audible clicks you get when a QAudioSink restarts from
IdleState.

Per-client backlog is capped at 2 s (older bytes are dropped when a
client outruns the mixer), and streams that have been silent for 10 s
are pruned so the client registry doesn't grow.
"""
from __future__ import annotations
import array
import math
import random
import struct
import time
from dataclasses import dataclass, field
from typing import Optional

from PySide6.QtCore      import QBuffer, QByteArray, QIODevice, QObject, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudio, QAudioFormat, QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer,
)


FX_SR   = 44100
TALK_SR = 16000
TALK_CHUNK_MS   = 20                        # mixer pump interval
TALK_CHUNK_N    = TALK_SR * TALK_CHUNK_MS // 1000   # 320 samples per pump
TALK_CHUNK_B    = TALK_CHUNK_N * 2                  # 640 bytes
TALK_MAX_BACKLOG_B = TALK_SR * 2 * 2                # 2 s of Int16 mono
TALK_IDLE_PRUNE_MS = 10_000                         # drop client after silent this long


# =====================================================
#  FX waveforms (unchanged from previous revision)
# =====================================================
def _bytes_int16(samples) -> bytes:
    out = array.array("h", [0] * len(samples))
    for i, s in enumerate(samples):
        if s > 1.0:  s = 1.0
        if s < -1.0: s = -1.0
        out[i] = int(s * 32767)
    return out.tobytes()


def _make_bomb(sr: int = FX_SR) -> bytes:
    dur = 1.6
    n = int(sr * dur)
    snd = [0.0] * n
    attack_n = int(sr * 0.025)
    for i in range(attack_n):
        snd[i] += (random.random() * 2 - 1) * (1.0 - i / attack_n) * 0.95
    for i in range(n):
        t = i / sr
        f = 60.0 * math.exp(-1.6 * t) + 30.0
        env = math.exp(-2.2 * t)
        snd[i] += math.sin(2 * math.pi * f * t) * env * 0.85
    for i in range(n):
        t = i / sr
        env = math.exp(-1.1 * t)
        snd[i] += (random.random() * 2 - 1) * env * 0.4
    for i in range(n):
        snd[i] = math.tanh(snd[i] * 1.4) * 0.9
    return _bytes_int16(snd)


def _make_cheer(sr: int = FX_SR) -> bytes:
    dur = 2.2
    n = int(sr * dur)
    snd = [0.0] * n
    for i in range(n):
        t = i / sr
        env_attack = 1.0 - math.exp(-12 * t)
        env_decay  = math.exp(-0.6 * t)
        env = env_attack * env_decay
        sparkle = 0.5 + 0.5 * math.sin(2 * math.pi * 17 * t + math.sin(23 * t))
        snd[i] = (random.random() * 2 - 1) * env * sparkle * 0.7
    for f_base in (261.63, 329.63, 392.00):
        for i in range(n):
            t = i / sr
            env = math.exp(-1.0 * t) * (1 - math.exp(-3 * t))
            snd[i] += math.sin(2 * math.pi * (f_base + 40 * t) * t) * env * 0.15
    for i in range(n):
        snd[i] = math.tanh(snd[i] * 1.1)
    return _bytes_int16(snd)


def _make_hearts(sr: int = FX_SR) -> bytes:
    dur = 1.4
    n = int(sr * dur)
    snd = [0.0] * n
    for offset_s, freq, amp in (
        (0.00,  784.0, 0.5), (0.10,  987.8, 0.45), (0.20, 1174.7, 0.40),
        (0.55,  587.3, 0.35), (0.55,  698.5, 0.30),
    ):
        start = int(offset_s * sr)
        for i in range(start, n):
            t = (i - start) / sr
            env = math.exp(-3.0 * t)
            snd[i] += math.sin(2 * math.pi * freq * t) * env * amp
            snd[i] += math.sin(2 * math.pi * freq * 2 * t) * env * amp * 0.15
    for i in range(n):
        snd[i] = math.tanh(snd[i] * 0.9) * 0.85
    return _bytes_int16(snd)


def _make_stars(sr: int = FX_SR) -> bytes:
    dur = 1.2
    n = int(sr * dur)
    snd = [0.0] * n
    notes = [1046.5, 1318.5, 1568.0, 2093.0, 1568.0, 1318.5, 1046.5]
    each = dur / len(notes)
    for idx, f in enumerate(notes):
        start = int(idx * each * sr)
        end = int(min(dur, (idx + 1) * each + 0.12) * sr)
        for i in range(start, end):
            t = (i - start) / sr
            env = math.exp(-6 * t) * (1 - math.exp(-60 * t))
            snd[i] += math.sin(2 * math.pi * f * t) * env * 0.4
            snd[i] += math.sin(2 * math.pi * f * 3.01 * t) * env * 0.15
    for i in range(n):
        snd[i] += (random.random() * 2 - 1) * 0.03 * math.exp(-i / n * 3)
    for i in range(n):
        snd[i] = math.tanh(snd[i] * 0.9) * 0.85
    return _bytes_int16(snd)


def _make_snow(sr: int = FX_SR) -> bytes:
    dur = 2.5
    n = int(sr * dur)
    snd = [0.0] * n
    prev = 0.0
    for i in range(n):
        t = i / sr
        raw = random.random() * 2 - 1
        prev = prev * 0.97 + raw * 0.03
        env = 0.5 + 0.5 * math.sin(2 * math.pi * 0.3 * t)
        snd[i] = prev * env * 0.5
    for offset_s, freq in ((0.3, 1567.0), (0.8, 1864.7), (1.4, 2093.0), (1.9, 1760.0)):
        start = int(offset_s * sr)
        for i in range(start, n):
            t = (i - start) / sr
            env = math.exp(-4.5 * t)
            snd[i] += math.sin(2 * math.pi * freq * t) * env * 0.25
    for i in range(n):
        snd[i] = math.tanh(snd[i] * 1.0) * 0.8
    return _bytes_int16(snd)


# =====================================================
#  Per-client TALK stream
# =====================================================
@dataclass
class _TalkStream:
    queue: bytearray = field(default_factory=bytearray)  # Int16 LE bytes
    last_chunk_ms: float = 0.0
    label: str = ""

    def push(self, data: bytes) -> None:
        self.queue.extend(data)
        self.last_chunk_ms = time.monotonic() * 1000
        # Keep Int16 alignment before capping.
        if len(self.queue) & 1:
            self.queue.append(0)
        if len(self.queue) > TALK_MAX_BACKLOG_B:
            drop = len(self.queue) - TALK_MAX_BACKLOG_B
            del self.queue[:drop]

    def take(self, n_samples: int) -> Optional[bytes]:
        """Pop up to n_samples worth of Int16 LE bytes.  Returns None when empty."""
        if not self.queue:
            return None
        want = n_samples * 2
        take = min(want, len(self.queue))
        out = bytes(self.queue[:take])
        del self.queue[:take]
        return out


# =====================================================
#  Engine — FX one-shots + TALK mixer
# =====================================================
class AudioEngine(QObject):

    def __init__(self) -> None:
        super().__init__()
        self._volume = 0.8
        self._fx_cache: dict[str, bytes] = {}
        self._fx_buffer: Optional[QBuffer] = None
        self._fx_sink: Optional[QAudioSink] = None

        self._talk_sink: Optional[QAudioSink] = None
        self._talk_io:   Optional[QIODevice]  = None
        self._streams:   dict[str, _TalkStream] = {}
        # Pre-allocated accumulator — reused each pump to keep GC quiet.
        self._mix_accum: list[int] = [0] * TALK_CHUNK_N
        # Keep the sink warm by writing silence whenever the mixer is idle,
        # but only for a short post-speech window (avoids unnecessary work).
        self._last_data_ms: float = 0.0

        self._build_talk_sink()

        self._pump_timer = QTimer(self)
        self._pump_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._pump_timer.setInterval(TALK_CHUNK_MS)
        self._pump_timer.timeout.connect(self._pump)
        self._pump_timer.start()

        # MP3 / WAV playback via the Qt high-level media pipeline.
        # Created lazily on first use so hosts without codec DLLs don't
        # fail at boot.
        self._file_player: Optional[QMediaPlayer] = None
        self._file_output: Optional[QAudioOutput] = None

    # ---------- volume ----------
    def set_volume(self, v: int) -> None:
        self._volume = max(0, min(100, int(v))) / 100.0
        if self._fx_sink:
            self._fx_sink.setVolume(self._volume)
        if self._talk_sink:
            self._talk_sink.setVolume(self._volume)
        if self._file_output:
            self._file_output.setVolume(self._volume)

    # ---------- audio-file playback (uploaded MP3 etc.) ----------
    # Uploaded audio loops forever; only the operator's 表示削除 button
    # stops it (matches the persistent-background semantic for images/video).
    def _ensure_file_player(self) -> None:
        if self._file_player is not None:
            return
        self._file_output = QAudioOutput(self)
        self._file_output.setVolume(self._volume)
        self._file_player = QMediaPlayer(self)
        self._file_player.setAudioOutput(self._file_output)
        try:
            self._file_player.setLoops(QMediaPlayer.Loops.Infinite)
        except AttributeError:
            self._file_player.setLoops(-1)
        self._file_player.errorOccurred.connect(
            lambda err, msg: print(f"[audio-file] error {err}: {msg}"))

    def is_audio_file_playing(self) -> bool:
        if self._file_player is None:
            return False
        return self._file_player.playbackState() == \
               QMediaPlayer.PlaybackState.PlayingState

    @Slot(str)
    def play_audio_file(self, path: str) -> None:
        self._ensure_file_player()
        assert self._file_player is not None
        self._file_player.stop()
        self._file_player.setSource(QUrl.fromLocalFile(path))
        self._file_player.play()

    @Slot()
    def stop_audio_file(self) -> None:
        if self._file_player is not None:
            self._file_player.stop()
            self._file_player.setSource(QUrl())

    # ---------- FX ----------
    def _fx_bytes(self, kind: str) -> bytes:
        if kind in self._fx_cache:
            return self._fx_cache[kind]
        makers = {
            "bomb":   _make_bomb,  "clap":   _make_cheer,
            "hearts": _make_hearts, "stars":  _make_stars, "snow": _make_snow,
        }
        fn = makers.get(kind)
        if fn is None:
            return b""
        data = fn(FX_SR)
        self._fx_cache[kind] = data
        return data

    def preload(self) -> None:
        for k in ("bomb", "clap", "hearts", "stars", "snow"):
            self._fx_bytes(k)

    @Slot(str)
    def play_fx(self, kind: str) -> None:
        data = self._fx_bytes(kind)
        if not data:
            return
        if self._fx_sink is not None:
            self._fx_sink.stop()
        self._fx_sink = _make_sink(FX_SR)
        self._fx_sink.setVolume(self._volume)
        self._fx_buffer = QBuffer()
        self._fx_buffer.setData(QByteArray(data))
        self._fx_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        self._fx_sink.start(self._fx_buffer)

    # ---------- TALK ----------
    def _build_talk_sink(self) -> None:
        self._talk_sink = _make_sink(TALK_SR)
        self._talk_sink.setVolume(self._volume)
        self._talk_io = self._talk_sink.start()

    def play_talk_chunk(self, cid: str, label: str, ip: str,
                        data: bytes, sr: int) -> None:
        """Slot attached to WebBridge.talkChunk. Runs on the Qt main thread."""
        if not data:
            return
        if sr != TALK_SR and sr > 0:
            data = _resample_int16le(data, sr, TALK_SR)
        # Align to Int16 boundary so later reads don't split a sample.
        if len(data) & 1:
            data = data[:-1]
        if not data:
            return
        stream = self._streams.get(cid)
        if stream is None:
            stream = _TalkStream(label=label or cid[:8])
            self._streams[cid] = stream
        else:
            if label:
                stream.label = label
        stream.push(data)

    # ---------- mixer pump (runs on Qt main thread, 20 ms tick) ----------
    def _pump(self) -> None:
        if self._talk_io is None or not self._talk_io.isOpen():
            self._build_talk_sink()
            if self._talk_io is None:
                return

        now_ms = time.monotonic() * 1000

        # Keep writing while there's room *and* any stream has samples ready.
        # bytesFree() gives us the sink's remaining buffer — writing beyond
        # that can block or get dropped, so we honor it as backpressure.
        safety_writes = 0
        while safety_writes < 8:
            free = self._talk_sink.bytesFree()
            if free < TALK_CHUNK_B:
                break

            any_active = False
            accum = self._mix_accum
            for i in range(TALK_CHUNK_N):
                accum[i] = 0

            for stream in self._streams.values():
                if not stream.queue:
                    continue
                data = stream.take(TALK_CHUNK_N)
                if not data:
                    continue
                n = len(data) // 2
                # Unpack Int16 LE into a Python tuple once per stream.
                samples = struct.unpack("<%dh" % n, data)
                for i, s in enumerate(samples):
                    accum[i] += s
                any_active = True

            if any_active:
                # Saturating clip to Int16. For N concurrent speakers the sum
                # can exceed the range; clipping is quicker than tracking N and
                # is imperceptible in brief overlap.
                out = array.array("h", [
                    32767 if s > 32767 else (-32768 if s < -32768 else s)
                    for s in accum
                ])
                try:
                    self._talk_io.write(out.tobytes())
                except Exception:
                    self._build_talk_sink()
                    break
                self._last_data_ms = now_ms
                safety_writes += 1
                continue

            # Nothing active this tick. If we very recently had speech, write
            # silence to keep the sink warm (no restart clicks). Otherwise
            # let it idle — bytesFree() stays at max and no CPU is wasted.
            if now_ms - self._last_data_ms < 1000.0:
                try:
                    self._talk_io.write(b"\x00" * TALK_CHUNK_B)
                except Exception:
                    self._build_talk_sink()
                    break
            break

        # Prune clients that have been silent for a while so the dict doesn't
        # grow without bound. Leaves the log alone — just cleans our mixer.
        if self._streams:
            dead = [cid for cid, s in self._streams.items()
                    if not s.queue and now_ms - s.last_chunk_ms > TALK_IDLE_PRUNE_MS]
            for cid in dead:
                self._streams.pop(cid, None)

    # ---------- introspection (used by unit tests) ----------
    def active_talkers(self) -> int:
        return sum(1 for s in self._streams.values() if s.queue)


# =====================================================
#  helpers
# =====================================================
def _make_sink(sr: int) -> QAudioSink:
    fmt = QAudioFormat()
    fmt.setSampleRate(sr)
    fmt.setChannelCount(1)
    fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    dev = QMediaDevices.defaultAudioOutput()
    sink = QAudioSink(dev, fmt)
    sink.setBufferSize(sr * 2 // 10)   # ~100 ms headroom
    return sink


def _resample_int16le(data: bytes, src_sr: int, dst_sr: int) -> bytes:
    if src_sr == dst_sr:
        return data
    n_src = len(data) // 2
    if n_src < 2:
        return data
    samples = struct.unpack("<%dh" % n_src, data)
    ratio = src_sr / dst_sr
    n_dst = max(1, int(n_src / ratio))
    out = array.array("h", [0] * n_dst)
    for i in range(n_dst):
        x = i * ratio
        i0 = int(x)
        frac = x - i0
        s0 = samples[i0] if i0 < n_src else 0
        s1 = samples[i0 + 1] if i0 + 1 < n_src else s0
        out[i] = int(s0 + (s1 - s0) * frac)
    return out.tobytes()
