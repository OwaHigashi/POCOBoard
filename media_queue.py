"""Media queue — holds uploaded image/video/audio files waiting for playback.

Uploads from the browser no longer play automatically.  They land here
first so the operator can review, reorder, or drop items before letting
them onto the stage.  The control-window 「キュー」 tab drives this.

Playback rules:
  * **image** and **video** share the "visual" slot on the display — only
    one visual plays at a time.
  * **audio** plays alongside visuals in its own slot.
  * Playing an item *removes* it from the waiting list and marks it as
    the current playing item.  The file stays on disk so the media layer
    can keep reading it.
  * 停止 clears both playing slots; the backing files stay in the cache
    (which auto-prunes old entries on its own).
"""
from __future__ import annotations
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal


# File-name prefix produced by web_server.py when it saves uploads —
# "<YYYYMMDD-HHMMSS>_<hex6>_<original.ext>". Strip to show the original.
_UPLOAD_PREFIX_RE = re.compile(r"^\d{8}-\d{6}_[0-9a-f]{6,8}_(.+)$")


@dataclass
class QueueItem:
    id:        str        # short uuid
    kind:      str        # 'image' | 'video' | 'audio'
    path:      str        # full path on disk
    filename:  str        # display name (original)
    size:      int        # bytes
    sender:    str        # e.g. "Alice (#abcd1234)"
    added_ms:  float
    cid:       str = ""   # uploader client_id (for per-user stop/cancel)


class MediaQueue(QObject):
    """Per-process media waiting list + current-playing registry.

    Lives in the Qt main thread; bridge signals reach us via queued
    connections so enqueue() is safe to call from any thread.
    """

    changed = Signal()    # emitted on every mutation (queue or playing slot)

    def __init__(self) -> None:
        super().__init__()
        self._items: list[QueueItem] = []
        self._playing_visual: Optional[QueueItem] = None
        self._playing_audio:  Optional[QueueItem] = None

    # ---------- inbound ----------
    def enqueue(self, kind: str, path: str, sender: str,
                cid: str = "") -> QueueItem:
        try:
            size = os.path.getsize(path)
        except OSError:
            size = 0
        raw_name = os.path.basename(path)
        m = _UPLOAD_PREFIX_RE.match(raw_name)
        display_name = m.group(1) if m else raw_name
        item = QueueItem(
            id=uuid.uuid4().hex[:10],
            kind=kind,
            path=path,
            filename=display_name,
            size=size,
            sender=sender or "?",
            added_ms=time.time() * 1000,
            cid=cid or "",
        )
        self._items.append(item)
        self.changed.emit()
        return item

    def remove_by_cid(self, cid: str) -> list[QueueItem]:
        """Drop every queued item uploaded by `cid` and delete its file.

        Used by the per-client "自分の投稿を取消" button in the browser.
        """
        if not cid:
            return []
        dropped: list[QueueItem] = []
        kept: list[QueueItem] = []
        for it in self._items:
            if it.cid == cid:
                dropped.append(it)
                try:
                    os.remove(it.path)
                except OSError:
                    pass
            else:
                kept.append(it)
        if dropped:
            self._items = kept
            self.changed.emit()
        return dropped

    # ---------- queries ----------
    def items(self) -> list[QueueItem]:
        return list(self._items)

    def playing_visual(self) -> Optional[QueueItem]:
        return self._playing_visual

    def playing_audio(self) -> Optional[QueueItem]:
        return self._playing_audio

    def count(self) -> int:
        return len(self._items)

    def protected_paths(self) -> set[str]:
        """Files that must not be pruned from the upload cache yet."""
        out = {it.path for it in self._items}
        if self._playing_visual is not None:
            out.add(self._playing_visual.path)
        if self._playing_audio is not None:
            out.add(self._playing_audio.path)
        return out

    # ---------- mutations ----------
    def remove(self, item_id: str) -> Optional[QueueItem]:
        """Drop a queued item (and delete its file — it was never played)."""
        for i, it in enumerate(self._items):
            if it.id == item_id:
                self._items.pop(i)
                try:
                    os.remove(it.path)
                except OSError:
                    pass
                self.changed.emit()
                return it
        return None

    def take(self, item_id: str) -> Optional[QueueItem]:
        """Pop an item without deleting its file — caller is about to play it."""
        for i, it in enumerate(self._items):
            if it.id == item_id:
                self._items.pop(i)
                self.changed.emit()
                return it
        return None

    def clear(self) -> int:
        """Empty the waiting list (not the playing slots). Returns # dropped."""
        n = len(self._items)
        for it in self._items:
            try:
                os.remove(it.path)
            except OSError:
                pass
        self._items.clear()
        self.changed.emit()
        return n

    def mark_playing(self, item: QueueItem) -> None:
        """Record that `item` is now on the display or the speakers."""
        if item.kind in ("image", "video"):
            self._playing_visual = item
        elif item.kind == "audio":
            self._playing_audio = item
        self.changed.emit()

    def clear_playing_visual(self) -> None:
        if self._playing_visual is None:
            return
        self._playing_visual = None
        self.changed.emit()

    def clear_playing_audio(self) -> None:
        if self._playing_audio is None:
            return
        self._playing_audio = None
        self.changed.emit()

    def stop_all(self) -> None:
        """Clear both playing slots — called from the 停止 button."""
        changed = self._playing_visual is not None or self._playing_audio is not None
        self._playing_visual = None
        self._playing_audio = None
        if changed:
            self.changed.emit()
