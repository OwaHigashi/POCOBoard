"""HTTP server in a background thread; talks to Qt via signals.

Endpoints:
  GET  /                 remote-control webpage  (sets `poco_client` cookie)
  GET  /status           JSON: accept, volume, clients, marquee, me
  POST /bomb /clap /hearts /stars /snow /petals /aurora /laser /sunset /leaves /notes /rainbow   FX triggers
  POST /talk             Int16LE mono PCM streamed to speaker (mixed)
  POST /marquee          UTF-8 text with markup → scrolling lane
  POST /marquee/stop     stops all marquee lanes
  POST /ai               おわくさ (AI) screen-buffer commands — JSON body
                         {"cmd": "say"|"comment"|"marquee"|"clear"|"mode"|
                                 "size"|"fx"|"marquee_stop", ...}
                         or {"cmds": [ ...several of the above... ]}.
                         Optional shared secret: config ai_token, sent as
                         header X-Poco-AI-Token (or ?token=).  Not subject to
                         the ACCEPT switch / client blocks — it is the
                         operator's own agent (see README "AI / COMMENT").
  GET  /ai/status        JSON: text mode, feed count, sizes
  POST /name             persist display name (sets `poco_name` cookie)
  POST /upload           upload a media file (image / video / audio)
                         ?type=image|video|audio&filename=foo.jpg
                         Content-Type: the file's MIME type
                         Body: raw binary bytes

Every request is identified by a `poco_client` cookie (16-hex random string
set on first visit).  Per-client `blocked` flag gates FX / marquee / talk /
upload: blocked clients get 403 `blocked`.  Blocking can also be per-IP
(the client IP honours X-Forwarded-For, so it works behind the reverse
proxy too — cookie resets can't dodge an IP block).  Separate global `accept=false`
returns 503 `disabled`.
"""
from __future__ import annotations
from collections import deque
import json
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing      import Optional
from urllib.parse import urlparse, parse_qs, quote, unquote

from PySide6.QtCore import QObject, QTimer, Signal

from webpage import INDEX_HTML


# ---------- allowed upload types ----------
_UPLOAD_LIMITS = {
    "image":  25 * 1024 * 1024,        # 25 MB per photo
    "video": 200 * 1024 * 1024,        # 200 MB per clip
    "audio":  50 * 1024 * 1024,        # 50 MB per track
}

_SAFE_EXT = {
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"},
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".wmv"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"},
}

_SANITIZE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_TALK_QUEUE_MAX_ITEMS = 128
_TALK_QUEUE_MAX_BYTES = 2 * 1024 * 1024
# Per-recv timeout for short endpoints (status, FX, talk, marquee, name).
# Streamed uploads use a longer timeout — set in _read_body_streamed —
# so that reverse proxies that buffer the request body (Nginx default)
# don't kill big uploads partway through.
_HTTP_REQUEST_TIMEOUT_SEC = 5.0
_UPLOAD_RECV_TIMEOUT_SEC  = 60.0


def _sanitize_filename(name: str, kind: str) -> str:
    base, ext = os.path.splitext(os.path.basename(name or ""))
    ext = ext.lower()
    if ext not in _SAFE_EXT.get(kind, set()):
        defaults = {"image": ".jpg", "video": ".mp4", "audio": ".mp3"}
        ext = defaults.get(kind, ".bin")
    base = _SANITIZE_NAME.sub("_", base)[:40] or "upload"
    return base + ext


class WebBridge(QObject):
    """Thread-safe signal bridge between HTTP worker threads and Qt."""

    fxRequested      = Signal(str, str, str, str)
    talkChunk        = Signal(str, str, str, bytes, int)
    marqueeRequested = Signal(str, str, str, str, int)
    marqueeStop      = Signal(str, str, str)
    # (client_id, label, ip, type, absolute path on disk)
    mediaUploaded    = Signal(str, str, str, str, str)
    # Per-uploader "stop mine" — (client_id, kind).
    # kind ∈ {'image','video','audio','all'}.  A ControlWindow slot listens
    # and actually performs the stop if ownership still matches.
    myStopRequested  = Signal(str, str)
    # おわくさ AI command — (client_id, label, ip, command dict).  The
    # dict is validated in the handler (whitelisted cmd / bounded strings);
    # ControlWindow.on_ai_command executes it on the Qt thread.
    aiRequested      = Signal(str, str, str, object)
    # pre-formatted log line
    requestLogged    = Signal(str, str)
    # emitted whenever the client registry or any blocked flag changes
    clientsChanged   = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._accept = True
        self._volume = 80
        self._debounce_ms = 300
        # Per-kind upload size caps in bytes (config upload_limit_*_mb).
        self.upload_limits: dict[str, int] = dict(_UPLOAD_LIMITS)
        self._last_fx_ms = 0
        # When True, the operator has switched the display into piano-roll
        # mode.  The HTTP layer rejects image / video uploads with
        # 503 piano_mode and surfaces the flag in /status so the browser UI
        # can grey out the corresponding upload buttons.
        self._piano_mode = False
        # COMMENT / MARQUEE text mode + feed size, mirrored from the display
        # so /status and /ai/status can report them; ai_token gates /ai.
        self._text_mode = "marquee"
        self._comment_count = 0
        self._comment_scale_pct = 100
        self._marquee_scale_pct = 100
        self._ai_token = ""
        self._last_ai_ms = 0.0
        # Known clients — client_id -> {name, last_seen_ms, ip, blocked}
        self._clients: dict[str, dict] = {}
        # IPs blocked outright (operator action).  Checked alongside the
        # per-cookie flag; survives the client getting a fresh cookie id.
        self._blocked_ips: set[str] = set()
        self._last_talk_log: dict[str, float] = {}
        self._marquee_lanes_used = 0
        self._marquee_lanes_max  = 0
        self._talk_queue = deque()
        self._talk_queue_bytes = 0
        # Ownership of the currently playing media slots.  Written by
        # ControlWindow as display/audio ownership changes; read by HTTP
        # handlers on the /my/status and /my/stop endpoints.  Empty string
        # means "nothing of that kind is playing".
        self._owners: dict[str, str] = {"image": "", "video": "", "audio": ""}

        # Drain HTTP-originated TALK chunks on the Qt thread with a bounded
        # in-process queue so worker threads cannot flood queued Qt signals.
        self._talk_timer = QTimer(self)
        self._talk_timer.setInterval(10)
        self._talk_timer.timeout.connect(self._drain_talk_queue)
        self._talk_timer.start()

    # ---- status / volume / accept ----
    def snapshot(self) -> dict:
        with self._lock:
            return {
                "accept":       self._accept,
                "volume":       self._volume,
                "clients":      self._active_client_count(time.time() * 1000),
                "marquee_used": self._marquee_lanes_used,
                "marquee_max":  self._marquee_lanes_max,
            }

    def _active_client_count(self, now_ms: float) -> int:
        return sum(1 for c in self._clients.values()
                   if now_ms - c.get("last_seen_ms", 0) < 30_000)

    def set_accept(self, v: bool) -> None:
        with self._lock:
            self._accept = bool(v)

    def set_volume(self, v: int) -> None:
        with self._lock:
            self._volume = max(0, min(100, int(v)))

    def set_debounce_ms(self, v: int) -> None:
        with self._lock:
            self._debounce_ms = max(0, int(v))

    def set_upload_limits(self, image_mb: int, video_mb: int,
                          audio_mb: int) -> None:
        """Per-kind upload caps in megabytes (0 or less = keep default)."""
        for kind, mb in (("image", image_mb), ("video", video_mb),
                         ("audio", audio_mb)):
            if mb and mb > 0:
                self.upload_limits[kind] = int(mb) * 1024 * 1024

    def fx_try_acquire(self, now_ms: int) -> bool:
        with self._lock:
            if not self._accept:
                return False
            if now_ms - self._last_fx_ms < self._debounce_ms:
                return False
            self._last_fx_ms = now_ms
            return True

    def is_accepting(self) -> bool:
        with self._lock:
            return self._accept

    def set_marquee_status(self, used: int, maximum: int) -> None:
        with self._lock:
            self._marquee_lanes_used = int(used)
            self._marquee_lanes_max = int(maximum)

    def set_piano_mode(self, on: bool) -> None:
        with self._lock:
            self._piano_mode = bool(on)

    # ---- AI / COMMENT mode ----
    def set_ai_token(self, token: str) -> None:
        with self._lock:
            self._ai_token = (token or "").strip()

    def ai_token_ok(self, presented: str) -> bool:
        with self._lock:
            want = self._ai_token
        if not want:
            return True
        return secrets.compare_digest(want, (presented or "").strip())

    def set_text_mode(self, mode: str) -> None:
        with self._lock:
            self._text_mode = "comment" if str(mode).startswith("c") else "marquee"

    def text_mode(self) -> str:
        with self._lock:
            return self._text_mode

    def set_comment_status(self, count: int) -> None:
        with self._lock:
            self._comment_count = int(count)

    def set_text_scales(self, marquee_pct: int, comment_pct: int) -> None:
        with self._lock:
            self._marquee_scale_pct = int(marquee_pct)
            self._comment_scale_pct = int(comment_pct)

    def ai_snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self._text_mode,
                "comment": {"count": self._comment_count,
                            "size_pct": self._comment_scale_pct},
                "marquee": {"used": self._marquee_lanes_used,
                            "size_pct": self._marquee_scale_pct},
                "last_ai_ms": int(self._last_ai_ms),
            }

    def note_ai(self) -> None:
        with self._lock:
            self._last_ai_ms = time.time() * 1000

    def is_piano_mode(self) -> bool:
        with self._lock:
            return self._piano_mode

    # ---- per-client media ownership ----
    def set_owner(self, kind: str, cid: str) -> None:
        kind = (kind or "").lower()
        if kind not in ("image", "video", "audio"):
            return
        with self._lock:
            self._owners[kind] = cid or ""

    def owner_of(self, kind: str) -> str:
        kind = (kind or "").lower()
        with self._lock:
            return self._owners.get(kind, "")

    def my_active_kinds(self, cid: str) -> dict[str, bool]:
        """Which media slots are currently held by `cid`."""
        if not cid:
            return {"image": False, "video": False, "audio": False}
        with self._lock:
            return {k: (v == cid) for k, v in self._owners.items()}

    # ---- client registry ----
    def touch_client(self, client_id: str, name: str, ip: str) -> tuple[bool, str]:
        now_ms = time.time() * 1000
        changed = False
        with self._lock:
            rec = self._clients.get(client_id)
            is_new = rec is None
            if rec is None:
                rec = {"name": name, "ip": ip, "last_seen_ms": now_ms,
                       "first_seen_ms": now_ms, "blocked": False}
                self._clients[client_id] = rec
                changed = True
            else:
                if name and rec.get("name") != name:
                    rec["name"] = name
                    changed = True
                rec["ip"] = ip
                rec["last_seen_ms"] = now_ms
        short = client_id[:8] if client_id else "anon"
        name_val = rec.get("name") or ""
        label = f"{name_val} (#{short})" if name_val else f"#{short}"
        if changed:
            self.clientsChanged.emit()
        return is_new, label

    def list_clients(self) -> list[dict]:
        """Snapshot of the client registry for the control-window UI."""
        now_ms = time.time() * 1000
        with self._lock:
            out = []
            for cid, rec in self._clients.items():
                last_ms = rec.get("last_seen_ms", 0)
                out.append({
                    "id": cid,
                    "name":    rec.get("name", ""),
                    "ip":      rec.get("ip", ""),
                    "blocked": bool(rec.get("blocked", False)),
                    "ip_blocked": rec.get("ip", "") in self._blocked_ips,
                    "idle_ms": int(now_ms - last_ms),
                    "first_seen_ms": rec.get("first_seen_ms", 0),
                })
        # newest-first by first_seen
        out.sort(key=lambda c: c["first_seen_ms"], reverse=True)
        return out

    def is_allowed(self, client_id: str, ip: str = "") -> tuple[bool, str]:
        """Returns (allowed, reason). reason ∈ {'ok','disabled','blocked'}."""
        with self._lock:
            if not self._accept:
                return False, "disabled"
            if ip and ip in self._blocked_ips:
                return False, "blocked"
            rec = self._clients.get(client_id)
            if rec is not None and rec.get("blocked"):
                return False, "blocked"
        return True, "ok"

    def set_ip_blocked(self, ip: str, blocked: bool) -> None:
        ip = (ip or "").strip()
        if not ip:
            return
        with self._lock:
            if blocked:
                self._blocked_ips.add(ip)
            else:
                self._blocked_ips.discard(ip)
        self.clientsChanged.emit()

    def is_ip_blocked(self, ip: str) -> bool:
        with self._lock:
            return ip in self._blocked_ips

    def set_blocked(self, client_id: str, blocked: bool) -> None:
        with self._lock:
            rec = self._clients.get(client_id)
            if rec is not None:
                rec["blocked"] = bool(blocked)
        self.clientsChanged.emit()

    def block_all(self) -> None:
        with self._lock:
            for rec in self._clients.values():
                rec["blocked"] = True
        self.clientsChanged.emit()

    def allow_all(self) -> None:
        with self._lock:
            for rec in self._clients.values():
                rec["blocked"] = False
            self._blocked_ips.clear()
        self.clientsChanged.emit()

    def forget_client(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)
        self.clientsChanged.emit()

    def should_log_talk(self, client_id: str, min_gap_ms: float = 2500.0) -> bool:
        now_ms = time.time() * 1000
        with self._lock:
            last = self._last_talk_log.get(client_id, 0.0)
            if now_ms - last >= min_gap_ms:
                self._last_talk_log[client_id] = now_ms
                return True
            return False

    def emit_log(self, kind: str, line: str) -> None:
        self.requestLogged.emit(kind, line)

    def submit_talk_chunk(self, cid: str, label: str, ip: str,
                          data: bytes, sr: int) -> bool:
        size = len(data)
        if size <= 0:
            return False
        with self._lock:
            if (len(self._talk_queue) >= _TALK_QUEUE_MAX_ITEMS or
                    self._talk_queue_bytes + size > _TALK_QUEUE_MAX_BYTES):
                return False
            self._talk_queue.append((cid, label, ip, data, sr))
            self._talk_queue_bytes += size
        return True

    def _drain_talk_queue(self) -> None:
        batch = []
        with self._lock:
            while self._talk_queue and len(batch) < 12:
                item = self._talk_queue.popleft()
                self._talk_queue_bytes -= len(item[3])
                batch.append(item)
        for cid, label, ip, data, sr in batch:
            self.talkChunk.emit(cid, label, ip, data, sr)


# =====================================================
#  Handler
# =====================================================
class _Handler(BaseHTTPRequestHandler):
    bridge:       WebBridge = None   # type: ignore[assignment]
    upload_dir:   str       = ""
    active_paths_cb = None

    def setup(self) -> None:
        super().setup()
        try:
            self.connection.settimeout(_HTTP_REQUEST_TIMEOUT_SEC)
        except Exception:
            pass

    def log_message(self, fmt: str, *args: object) -> None:
        return

    # --- cookies / identity ---
    def _parse_cookies(self) -> dict[str, str]:
        raw = self.headers.get("Cookie", "")
        out: dict[str, str] = {}
        if not raw:
            return out
        for piece in raw.split(";"):
            if "=" not in piece:
                continue
            k, v = piece.split("=", 1)
            out[k.strip()] = unquote(v.strip())
        return out

    def _identity(self) -> tuple[str, str, str, Optional[str]]:
        cookies = self._parse_cookies()
        cid = cookies.get("poco_client") or ""
        new_cookie = None
        if not cid or len(cid) < 8:
            cid = secrets.token_hex(8)
            new_cookie = cid
        # Clients percent-encode this header (HTTP headers are latin-1 only,
        # so raw Japanese names can't travel in them).
        hdr_name = unquote(self.headers.get("X-Poco-Name", "")).strip()
        name = hdr_name or cookies.get("poco_name", "").strip()
        if len(name) > 32:
            name = name[:32]
        ip = self.client_address[0] if self.client_address else "?"
        # Behind the reverse proxy every socket peer is the proxy itself;
        # the real client IP travels in X-Forwarded-For (first hop).
        fwd = self.headers.get("X-Forwarded-For", "")
        if fwd:
            first = fwd.split(",")[0].strip()
            if first:
                ip = first
        return cid, name, ip, new_cookie

    def _set_identity_cookie(self, cid: str) -> None:
        self.send_header(
            "Set-Cookie",
            f"poco_client={cid}; Path=/; SameSite=Lax; Max-Age=31536000",
        )

    def _send_json(self, code: int, obj: dict,
                   set_cookie: Optional[str] = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self._set_identity_cookie(set_cookie)
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError, socket.timeout, OSError):
            pass

    def _read_body(self, max_bytes: int) -> bytes:
        # Reverse proxies sometimes switch a POST to Transfer-Encoding:
        # chunked and drop the Content-Length header — in which case the
        # simple self.rfile.read(n) path below fails with n=0 and we'd
        # return an empty body.  Handle both.
        te = self.headers.get("Transfer-Encoding", "").lower()
        if "chunked" in te:
            out = bytearray()
            while True:
                try:
                    size_line = self.rfile.readline().strip()
                except (socket.timeout, OSError):
                    return b""
                if not size_line:
                    break
                try:
                    size = int(size_line.split(b";")[0], 16)
                except ValueError:
                    break
                if size == 0:
                    # discard trailers
                    while True:
                        try:
                            trailer = self.rfile.readline().strip()
                        except (socket.timeout, OSError):
                            return b""
                        if not trailer:
                            break
                    break
                if len(out) + size > max_bytes:
                    return b""
                try:
                    out.extend(self.rfile.read(size))
                    self.rfile.read(2)   # CRLF after chunk
                except (socket.timeout, OSError):
                    return b""
            return bytes(out)
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > max_bytes:
            return b""
        try:
            return self.rfile.read(n)
        except (socket.timeout, OSError):
            return b""

    def _read_body_streamed(self, dest_path: str, max_bytes: int) -> int:
        """Stream the request body straight to disk — used for uploads so
        we don't buffer huge videos in RAM.  Returns bytes written, or -1
        if Content-Length is missing / too large.
        """
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return -1
        if n <= 0 or n > max_bytes:
            return -1
        # Uploads can sit silent for tens of seconds when a buffering reverse
        # proxy (Nginx with proxy_request_buffering on) is between client and
        # us — extend the per-recv timeout for the body read, then restore.
        prev_timeout = None
        try:
            prev_timeout = self.connection.gettimeout()
            self.connection.settimeout(_UPLOAD_RECV_TIMEOUT_SEC)
        except Exception:
            pass
        remaining = n
        written = 0
        try:
            with open(dest_path, "wb") as f:
                while remaining > 0:
                    try:
                        chunk = self.rfile.read(min(64 * 1024, remaining))
                    except (socket.timeout, OSError):
                        return -1
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
                    remaining -= len(chunk)
        finally:
            try:
                self.connection.settimeout(prev_timeout)
            except Exception:
                pass
        return written

    def _touch(self, cid: str, name: str, ip: str) -> str:
        """Register/refresh the client and log JOIN the first time it is
        seen.  GET / and /status used to call touch_client directly, so
        the registration happened silently on page load and the JOIN line
        never appeared (by the first POST the client was no longer new)."""
        is_new, label = self.bridge.touch_client(cid, name, ip)
        if is_new:
            now = time.strftime("%H:%M:%S")
            self.bridge.emit_log("JOIN", f"{now}  {label:24s}  JOIN      {ip}")
        return label

    def _who(self) -> tuple[str, str, str, Optional[str]]:
        cid, name, ip, new_cookie = self._identity()
        label = self._touch(cid, name, ip)
        return cid, label, ip, new_cookie

    # ===== GET =====
    def do_GET(self) -> None:
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            cid, name, ip, new_cookie = self._identity()
            self._touch(cid, name, ip)
            body = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            if new_cookie:
                self._set_identity_cookie(new_cookie)
            self.end_headers()
            self.wfile.write(body)
            return
        if u.path == "/status":
            cid, name, ip, new_cookie = self._identity()
            self._touch(cid, name, ip)
            snap = self.bridge.snapshot()
            allowed, _ = self.bridge.is_allowed(cid, ip)
            mine = self.bridge.my_active_kinds(cid)
            self._send_json(200, {
                "accept":  snap["accept"],
                "volume":  snap["volume"],
                "clients": snap["clients"],
                "marquee": {"used": snap["marquee_used"],
                            "max":  snap["marquee_max"]},
                "me":   {"id": cid, "name": name, "allowed": allowed},
                "mine": mine,
                # piano_mode is informational only — uploads are no
                # longer rejected; the browser uses this to surface a
                # tiny "🎹 演出中" hint so users know their photo /
                # video will appear translucently on top of the keyboard.
                "piano_mode": self.bridge.is_piano_mode(),
                "text_mode": self.bridge.text_mode(),
            }, set_cookie=new_cookie)
            return
        if u.path == "/ai/status":
            if not self._ai_authorized(parse_qs(u.query or "")):
                return
            snap = self.bridge.ai_snapshot()
            snap["ok"] = True
            self._send_json(200, snap)
            return
        self._send_json(404, {"ok": False, "reason": "not_found"})

    # ===== AI (おわくさ) =====
    _AI_CMDS = {"say", "comment", "marquee", "clear", "mode", "size", "fx",
                "marquee_stop"}
    _AI_FX = {"bomb", "clap", "cheer", "hearts", "stars", "snow", "petals",
              "aurora", "laser", "sunset", "leaves", "notes", "rainbow"}
    _AI_MAX_TEXT = 2000

    def _ai_authorized(self, query: dict) -> bool:
        tok = self.headers.get("X-Poco-AI-Token", "") or (query.get("token", [""])[0])
        if self.bridge.ai_token_ok(tok):
            return True
        self._send_json(403, {"ok": False, "reason": "bad_token"})
        return False

    @classmethod
    def _ai_normalize(cls, c) -> Optional[dict]:
        """Whitelist + bound one command.  Returns None when unusable."""
        if not isinstance(c, dict):
            return None
        cmd = str(c.get("cmd", "")).strip().lower()
        if cmd not in cls._AI_CMDS:
            return None
        out: dict = {"cmd": cmd}
        M = cls._AI_MAX_TEXT

        def _s(v, n=M) -> str:
            return str(v if v is not None else "")[:n]

        if cmd in ("say", "comment"):
            lines = c.get("lines")
            if isinstance(lines, list):
                norm = []
                for ln in lines[:20]:
                    if isinstance(ln, dict):
                        norm.append({"who": _s(ln.get("who"), 64),
                                     "text": _s(ln.get("text")),
                                     "kind": _s(ln.get("kind"), 16) or "text"})
                    else:
                        norm.append({"who": "", "text": _s(ln), "kind": "text"})
                out["lines"] = [l for l in norm if l["text"] or l["who"]]
            else:
                out["lines"] = [{"who": _s(c.get("who"), 64),
                                 "text": _s(c.get("text")),
                                 "kind": _s(c.get("kind"), 16) or "text"}]
            if not out["lines"] or not any(l["text"] or l["who"] for l in out["lines"]):
                return None
            try:
                out["speed"] = max(1, min(5, int(c.get("speed", 1))))
            except (TypeError, ValueError):
                out["speed"] = 1
        elif cmd == "marquee":
            out["text"] = _s(c.get("text")).strip()
            if not out["text"]:
                return None
            try:
                out["speed"] = max(1, min(5, int(c.get("speed", 1))))
            except (TypeError, ValueError):
                out["speed"] = 1
        elif cmd == "clear":
            t = _s(c.get("target"), 16).lower() or "all"
            out["target"] = t if t in ("all", "comment", "marquee") else "all"
        elif cmd == "mode":
            m = _s(c.get("mode"), 16).lower()
            if m.startswith("c"):
                out["mode"] = "comment"
            elif m.startswith("m"):
                out["mode"] = "marquee"
            elif m in ("toggle", "switch", ""):
                out["mode"] = "toggle"
            else:
                return None
        elif cmd == "size":
            t = _s(c.get("target"), 16).lower()
            out["target"] = t if t in ("comment", "marquee", "both") else ""
            pct = c.get("pct")
            delta = c.get("delta")
            try:
                if pct is not None:
                    out["pct"] = max(50, min(500, int(pct)))
                elif delta is not None:
                    out["delta"] = max(-450, min(450, int(delta)))
                else:
                    return None
            except (TypeError, ValueError):
                return None
        elif cmd == "fx":
            k = _s(c.get("kind"), 16).lower()
            if k == "cheer":
                k = "clap"
            if k not in cls._AI_FX:
                return None
            out["kind"] = k
        return out

    def _handle_ai(self, query: dict) -> None:
        if not self._ai_authorized(query):
            return
        cid, label, ip, new_cookie = self._who()
        body = self._read_body(256 * 1024)
        if not body:
            self._send_json(400, {"ok": False, "reason": "empty"}, set_cookie=new_cookie)
            return
        try:
            j = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"ok": False, "reason": "bad_json"}, set_cookie=new_cookie)
            return
        raw_cmds = j.get("cmds") if isinstance(j, dict) and isinstance(j.get("cmds"), list) else [j]
        cmds = []
        rejected = 0
        for c in raw_cmds[:32]:
            n = self._ai_normalize(c)
            if n is None:
                rejected += 1
            else:
                cmds.append(n)
        if not cmds:
            self._send_json(400, {"ok": False, "reason": "bad_cmd", "rejected": rejected},
                            set_cookie=new_cookie)
            return
        now_hms = time.strftime("%H:%M:%S")
        for c in cmds:
            self.bridge.aiRequested.emit(cid, label, ip, c)
            self.bridge.emit_log("AI", f"{now_hms}  {label:24s}  AI        {_ai_preview(c)}")
        self.bridge.note_ai()
        snap = self.bridge.ai_snapshot()
        self._send_json(200, {"ok": True, "n": len(cmds), "rejected": rejected,
                              "mode": snap["mode"]}, set_cookie=new_cookie)

    # ===== POST =====
    def _reject_if_not_allowed(self, cid: str, label: str, ip: str,
                               log_tag: str,
                               new_cookie: Optional[str]) -> bool:
        """Write 503/403 + log if this client may not act. Returns True when
        the request was rejected (caller should just return)."""
        allowed, reason = self.bridge.is_allowed(cid, ip)
        if allowed:
            return False
        now_hms = time.strftime("%H:%M:%S")
        self.bridge.emit_log(
            log_tag,
            f"{now_hms}  {label:24s}  {log_tag:<9s}  X REJECTED ({reason})")
        if reason == "disabled":
            self._send_json(503, {"ok": False, "reason": "disabled"},
                            set_cookie=new_cookie)
        else:
            self._send_json(403, {"ok": False, "reason": reason},
                            set_cookie=new_cookie)
        return True

    def do_POST(self) -> None:
        u = urlparse(self.path)
        path = u.path
        query = parse_qs(u.query or "")
        now_ms = int(time.time() * 1000)
        now_hms = time.strftime("%H:%M:%S")

        # /name — persist display name (never blocked)
        if path == "/name":
            cid, _, ip, new_cookie = self._identity()
            body = self._read_body(2048)
            name = ""
            try:
                j = json.loads(body.decode("utf-8") or "{}")
                name = str(j.get("name", "")).strip()[:32]
            except Exception:
                pass
            self._touch(cid, name, ip)
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            if new_cookie:
                self._set_identity_cookie(new_cookie)
            # Percent-encode: cookie values (like headers) must stay latin-1
            # safe; the browser side decodeURIComponent()s it back.
            self.send_header(
                "Set-Cookie",
                f"poco_name={quote(name)}; Path=/; SameSite=Lax; Max-Age=31536000",
            )
            payload = json.dumps({"ok": True, "id": cid, "name": name}).encode("utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            self.bridge.emit_log(
                "NAME",
                f"{now_hms}  #{cid[:8]:<22s}  NAME      -> {name!r}",
            )
            return

        fx_paths = {
            "/bomb":   ("bomb",   "BOMB"),
            "/clap":   ("clap",   "CHEER"),
            "/hearts": ("hearts", "HEARTS"),
            "/stars":  ("stars",  "STARS"),
            "/snow":   ("snow",   "SNOW"),
            "/petals": ("petals", "PETALS"),
            "/aurora": ("aurora", "AURORA"),
            "/laser":  ("laser",  "LASER"),
            "/sunset": ("sunset", "SUNSET"),
            "/leaves": ("leaves", "LEAVES"),
            "/notes":  ("notes",  "NOTES"),
            "/rainbow": ("rainbow", "RAINBOW"),
        }
        if path in fx_paths:
            cid, label, ip, new_cookie = self._who()
            kind, log_tag = fx_paths[path]
            if self._reject_if_not_allowed(cid, label, ip, log_tag, new_cookie):
                return
            if not self.bridge.fx_try_acquire(now_ms):
                self.bridge.emit_log(log_tag, f"{now_hms}  {label:24s}  {log_tag:<9s}  X busy (debounced)")
                self._send_json(429, {"ok": False, "reason": "busy"}, set_cookie=new_cookie)
                return
            self.bridge.fxRequested.emit(cid, label, ip, kind)
            self.bridge.emit_log(log_tag, f"{now_hms}  {label:24s}  {log_tag}")
            self._send_json(200, {"ok": True}, set_cookie=new_cookie)
            return

        if path == "/talk":
            cid, label, ip, new_cookie = self._who()
            if self._reject_if_not_allowed(cid, label, ip, "TALK", new_cookie):
                return
            data = self._read_body(256 * 1024)   # generous — reverse proxies can pad
            if not data:
                # Log the empty hit so the operator can see chunks ARE reaching
                # the server but with zero body (proxy buffering / header stripping).
                te_hdr = self.headers.get("Transfer-Encoding", "")
                cl_hdr = self.headers.get("Content-Length", "")
                self.bridge.emit_log(
                    "TALK",
                    f"{now_hms}  {label:24s}  TALK      X empty body  (CL={cl_hdr!r} TE={te_hdr!r})")
                self._send_json(400, {"ok": False, "reason": "empty"},
                                set_cookie=new_cookie)
                return
            try:
                sr = int(query.get("sr", ["16000"])[0])
            except ValueError:
                sr = 16000
            if sr < 8000 or sr > 48000:
                sr = 16000
            if not self.bridge.submit_talk_chunk(cid, label, ip, data, sr):
                self.bridge.emit_log(
                    "TALK",
                    f"{now_hms}  {label:24s}  TALK      X busy (server queue full)")
                self._send_json(429, {"ok": False, "reason": "busy"},
                                set_cookie=new_cookie)
                return
            if self.bridge.should_log_talk(cid):
                secs = len(data) // 2 / sr
                self.bridge.emit_log(
                    "TALK",
                    f"{now_hms}  {label:24s}  TALK      ({sr} Hz, {len(data)} B, ~{secs:.1f} s)",
                )
            self._send_json(200, {"ok": True}, set_cookie=new_cookie)
            return

        if path == "/marquee":
            cid, label, ip, new_cookie = self._who()
            if self._reject_if_not_allowed(cid, label, ip, "MARQUEE", new_cookie):
                return
            body = self._read_body(16 * 1024)
            if not body:
                self._send_json(400, {"ok": False, "reason": "empty"},
                                set_cookie=new_cookie)
                return
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                self._send_json(400, {"ok": False, "reason": "not_utf8"},
                                set_cookie=new_cookie)
                return
            try:
                speed = int(query.get("speed", ["1"])[0])
            except ValueError:
                speed = 1
            speed = max(1, min(5, speed))
            self.bridge.marqueeRequested.emit(cid, label, ip, text, speed)
            preview = text.replace("\n", " ")
            if len(preview) > 60:
                preview = preview[:57] + "..."
            self.bridge.emit_log(
                "MARQUEE",
                f"{now_hms}  {label:24s}  MARQUEE   x{speed}  {preview}",
            )
            self._send_json(200, {"ok": True}, set_cookie=new_cookie)
            return

        if path == "/ai":
            self._handle_ai(query)
            return

        if path == "/marquee/stop":
            cid, label, ip, new_cookie = self._who()
            self.bridge.marqueeStop.emit(cid, label, ip)
            self.bridge.emit_log("MARQUEE/STOP", f"{now_hms}  {label:24s}  MARQUEE   STOP")
            self._send_json(200, {"ok": True}, set_cookie=new_cookie)
            return

        if path == "/my/stop":
            # Stop / cancel uploads owned by *this* client only.  Other
            # clients may not affect items they did not upload.  Accepts
            # ?kind=image|video|audio|all; default = all.
            cid, label, ip, new_cookie = self._who()
            kind = (query.get("kind", ["all"])[0] or "all").lower()
            if kind not in ("image", "video", "audio", "all"):
                self._send_json(400, {"ok": False, "reason": "bad_kind"},
                                set_cookie=new_cookie)
                return
            # Verify at least one matching slot is owned by this client.
            mine = self.bridge.my_active_kinds(cid)
            if kind == "all":
                stopped = [k for k, v in mine.items() if v]
            else:
                stopped = [kind] if mine.get(kind) else []
            # Always forward to the main thread so the queue is swept too
            # (pending items uploaded by this client get removed), even if
            # none are currently playing.
            self.bridge.myStopRequested.emit(cid, kind)
            self.bridge.emit_log(
                "MY/STOP",
                f"{now_hms}  {label:24s}  MY/STOP   kind={kind}  stopped={','.join(stopped) or '-'}")
            self._send_json(200, {"ok": True, "stopped": stopped},
                            set_cookie=new_cookie)
            return

        if path == "/upload":
            cid, label, ip, new_cookie = self._who()
            if self._reject_if_not_allowed(cid, label, ip, "UPLOAD", new_cookie):
                return
            kind = (query.get("type", [""])[0] or "").lower()
            if kind not in self.bridge.upload_limits:
                self._send_json(400, {"ok": False, "reason": "bad_type"},
                                set_cookie=new_cookie)
                return
            # NOTE: piano-roll mode no longer rejects image / video uploads.
            # The display composites them as semi-transparent overlays on
            # top of the keyboard scene, so all four layers (roll +
            # image/video + FX + marquee) stay readable together.
            raw_name = query.get("filename", ["upload"])[0]
            safe_name = _sanitize_filename(raw_name, kind)
            # Build a disk path that includes timestamp + random token so
            # concurrent uploads from the same filename don't collide.
            stamp = time.strftime("%Y%m%d-%H%M%S")
            tok = secrets.token_hex(3)
            final_name = f"{stamp}_{tok}_{safe_name}"
            os.makedirs(self.upload_dir, exist_ok=True)
            dest = os.path.join(self.upload_dir, final_name)
            max_bytes = self.bridge.upload_limits[kind]
            written = self._read_body_streamed(dest, max_bytes)
            if written <= 0:
                try:
                    os.remove(dest)
                except OSError:
                    pass
                self._send_json(413, {"ok": False, "reason": "too_large_or_empty"},
                                set_cookie=new_cookie)
                return
            self.bridge.mediaUploaded.emit(cid, label, ip, kind, dest)
            self.bridge.emit_log(
                "UPLOAD",
                f"{now_hms}  {label:24s}  UPLOAD    {kind:<5s} {written//1024} KB  {safe_name}",
            )
            self._send_json(200, {"ok": True, "size": written}, set_cookie=new_cookie)
            self._prune_old_uploads()
            return

        self._send_json(404, {"ok": False, "reason": "not_found"})

    # Keep at most ~50 files in the upload cache so long sessions don't
    # quietly fill the disk.
    def _prune_old_uploads(self, max_files: int = 50) -> None:
        protected = set()
        try:
            if callable(self.active_paths_cb):
                protected = {os.path.abspath(p) for p in self.active_paths_cb() or []}
        except Exception:
            protected = set()
        try:
            entries = [
                (os.path.getmtime(os.path.join(self.upload_dir, n)),
                 os.path.abspath(os.path.join(self.upload_dir, n)),
                 n)
                for n in os.listdir(self.upload_dir)
                if os.path.isfile(os.path.join(self.upload_dir, n))
            ]
        except OSError:
            return
        prunable = [entry for entry in entries if entry[1] not in protected]
        if len(prunable) <= max_files:
            return
        prunable.sort()   # oldest first
        for _, path, name in prunable[:-max_files]:
            try:
                os.remove(path)
            except OSError:
                pass


def _ai_preview(c: dict) -> str:
    cmd = c.get("cmd", "?")
    if cmd in ("say", "comment"):
        first = c["lines"][0]
        txt = (first.get("who", "") + " " + first.get("text", "")).strip().replace("\n", " ")
        more = f" (+{len(c['lines']) - 1})" if len(c["lines"]) > 1 else ""
        return f"{cmd:<8s} {txt[:57] + '...' if len(txt) > 60 else txt}{more}"
    if cmd == "marquee":
        t = c["text"].replace("\n", " ")
        return f"marquee  x{c['speed']}  {t[:57] + '...' if len(t) > 60 else t}"
    if cmd == "clear":
        return f"clear    {c['target']}"
    if cmd == "mode":
        return f"mode     {c['mode']}"
    if cmd == "size":
        what = f"{c['pct']}%" if "pct" in c else f"{c['delta']:+d}%"
        return f"size     {c['target'] or 'auto'} {what}"
    if cmd == "fx":
        return f"fx       {c['kind']}"
    return cmd


def build_server(host: str, port: int, bridge: WebBridge,
                 upload_dir: str, active_paths_cb=None) -> ThreadingHTTPServer:
    handler_cls = type("_BoundHandler", (_Handler,),
                       {"bridge": bridge, "upload_dir": upload_dir,
                        "active_paths_cb": staticmethod(active_paths_cb) if active_paths_cb else None})
    server_cls = type(
        "_PocoThreadingHTTPServer",
        (ThreadingHTTPServer,),
        {"request_queue_size": 128, "allow_reuse_address": True},
    )
    return server_cls((host, port), handler_cls)


def run_in_thread(host: str, port: int, bridge: WebBridge,
                  upload_dir: str, active_paths_cb=None) -> tuple[ThreadingHTTPServer, threading.Thread]:
    srv = build_server(host, port, bridge, upload_dir, active_paths_cb=active_paths_cb)
    th = threading.Thread(target=srv.serve_forever, name="pocoboard-http", daemon=True)
    th.start()
    return srv, th
