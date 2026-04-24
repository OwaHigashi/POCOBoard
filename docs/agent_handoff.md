# Agent Handoff

Updated: 2026-04-25

## Summary

This repo was updated to improve stability around multi-user TALK audio mixing,
HTTP request handling under load, queue/playback state sync, and README/docs.

## Main code changes

- `web_server.py`
  - Added a bounded TALK ingest queue instead of unbounded queued Qt signals.
  - `/talk` now returns `429 busy` when the server-side TALK queue is full.
  - Added socket read timeout handling for slow or half-open clients.
  - Increased HTTP accept backlog and enabled address reuse.
  - Upload-cache pruning now skips files that are currently playing or still queued.
- `webpage.py`
  - Reduced TALK send chunk size from 500 ms to 200 ms.
  - Counted browser-side backpressure as a consecutive error so auto-recovery can trigger.
- `audio.py`
  - Added stall detection and sink rebuild logic for TALK output when writes stop progressing.
  - Treats zero/short writes as failure and rebuilds the sink.
  - Added `audioPlaybackStopped` signal.
  - Audio file playback errors now stop playback cleanly instead of leaving stale ownership.
- `display_window.py`
  - Added `visualPlaybackStopped` signal.
  - Video playback errors now stop playback cleanly.
  - Image clear / timeout paths now consistently clear visual ownership.
- `media_queue.py`
  - Added `protected_paths()` for cache-prune protection.
  - Added explicit clear methods for visual/audio now-playing state.
- `control_window.py`
  - Wired playback-stopped signals back into `MediaQueue`.
  - Avoids marking queue items as playing when the file is missing or the image failed to load.
- `pocoboard.py`
  - Passes queue/playing paths to the web server for prune protection.
  - Calls `server_close()` during shutdown.

## Documentation updates

- `README.md` was rewritten to match the current UI and behavior.
- Updated screenshots:
  - `docs/img/control_queue.png`
  - `docs/img/control_users.png`
  - `docs/img/control_marquee.png`
  - `docs/img/control_log.png`

## Verification performed

- `python -m py_compile audio.py web_server.py pocoboard.py control_window.py display_window.py media_queue.py config.py`
- TALK ingress emulation with `curl` / raw socket confirmed:
  - overload returns a mix of `200` and `429 busy`
  - server recovers after backlog drains
  - slow partial POST gets dropped by timeout

## Remaining recommended checks

- Real-device verification of TALK sink recovery on actual audio hardware.
- Multi-client simultaneous TALK on LAN.
- USB audio device disconnect / reconnect while running.
- Long session behavior with many uploads and repeated autoplay transitions.

## Post-review follow-ups (2026-04-25)

- `web_server.py`: kept the 5 s per-recv timeout for short endpoints, but
  extended it to 60 s for the streaming upload body and restored the
  previous timeout afterwards. The original blanket 5 s would break large
  uploads through reverse proxies that buffer the request body
  (Nginx default `proxy_request_buffering on`).
- `display_window.py` / `control_window.py`: `DisplayWindow.show_image`
  now returns `bool`; `_dispatch_play` uses that return value instead of
  inspecting the private `_bg_image` attribute. The previous check gave a
  false success when a corrupt new image was uploaded while a different
  image was already on screen (the old image stayed up and the check saw
  a non-None pixmap).
- `media_queue.py`: added a `threading.Lock` so `protected_paths()` can
  be called safely from the HTTP worker thread. All `MediaQueue`
  mutations and the cross-thread snapshot read now take the lock;
  filesystem deletions are performed outside the lock so disk latency
  does not block queue operations.
