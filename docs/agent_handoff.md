# Agent Handoff

Updated: 2026-04-30 (piano-mode MIDI stability hardening)

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

## UI follow-ups (2026-04-25)

- `control_window.py`
  - Restyled the control UI away from the original dark/high-contrast look.
  - Final direction is a bright, simple, elegant theme with stronger text
    contrast than the first light pass.
  - Added a header-level `システム終了` button on the top right.
  - `ACCEPT` now sits immediately to the left of `システム終了`.
- `webpage.py`
  - Restyled the browser-side remote UI to match the bright control-panel
    theme.
  - Preserved responsive behavior for narrow/mobile screens.

## FX scene refinement + rename (2026-04-25)

- `animations.py`: refined every visual effect for stronger production value.
  - **BOMB**: double-pulse strobe, multi-rim shockwave (3 rings), gradient ember
    streaks, ember rain after the blast, ground-level hot reflection.
  - **CHEER**: added curling streamer ribbons, confetti shape variety
    (rect / triangle / circle), spotlight cones from upper corners,
    more frequent / larger star bursts.
  - **HEARTS**: pulsing glow halo, glossy inner highlight, sparkle trail
    behind larger hearts, pink mist along the bottom, large bokeh hearts
    in the background.
  - **STARS**: long gradient trails on shooting stars, occasional larger
    "wishing stars" with cross-shaped twinkle highlights, twinkling
    background star field, faint nebula tint.
  - **SNOW**: replaced circle flakes with proper 6-arm snowflake glyphs,
    three depth layers (far / mid / near) for parallax, moonlight glow
    with a small moon disk, faint upper aurora hint.
  - **PETALS**: three depth layers, refined petal shape with subtle base
    notch, bokeh sparkle drift, blossom-branch silhouettes near the top
    corners, bright inner highlight on each petal.
  - **AURORA**: 4 ribbon bands (was 3) with vertical light pillars, full
    twinkling background star field, mountain skyline silhouette,
    subtle water-reflection band above the horizon.
  - **LASER**: 5 stage beams (was 3), volumetric haze cones, lens flares
    at both origin and target, occasional strobe flashes, expanded
    color palette.
- Renamed `SUMMER → SUNSET` and `AUTUMN → LEAVES` to match the SNOW
  pattern (concrete element noun, not season name).
  - **SUNSET**: refined sunset-on-sea scene with backlit cumulus clouds,
    radial sun rays, animated reflection shaft on the water, sailboat
    silhouette, three flapping V-shaped seabirds.
  - **LEAVES**: leaf silhouette is a petal-like elongated teardrop
    (`_maple_path`) with four rounded notches subtracted from the sides
    via `QPainterPath.subtracted()` — gives a lobed, leafy edge instead
    of a star. (Earlier draft used a 5-tip alternating-radius polygon
    that visually read as a star — fixed.) 5-color autumn palette, tree
    silhouettes flanking both edges, animated diagonal sun rays,
    leaf-pile accumulation along the ground.
- Endpoint paths and UI keys updated everywhere:
  - `web_server.py`: `/summer` → `/sunset`, `/autumn` → `/leaves`.
  - `audio.py`: `_make_summer` → `_make_sunset`, `_make_autumn` →
    `_make_leaves`; preload list and FX factory dict updated.
  - `webpage.py`: button IDs / classes / labels / trigger calls renamed.
  - `control_window.py`: button list, QPushButton classes, log tag map
    updated.
  - `README.md`: button list, descriptions, and HTTP API table updated.
- Verified: `py_compile` passes; all 10 scenes render 8 frames each
  through `QPainter` on a 800x450 `QImage` without exception.

## UX note: `自分のぜんぶ取消`

- Current behavior is intentionally not an "undo to previous visual" action.
- `display_window.py` treats image and video as mutually replacing visual
  backgrounds:
  - showing an image stops any active video
  - starting a video clears any active image
- Therefore, if a user uploads an image and then uploads a video, stopping
  the video does not restore the prior image; the display returns to the
  idle/empty state because the image was already cleared when the video
  started.
- The meaning of `自分のぜんぶ取消` in the current implementation is:
  - stop any currently active image/video/audio owned by that client
  - remove any queued media owned by that client
- This button is most meaningful when the same client owns multiple active
  media types and/or still has queued uploads waiting to play.
- The user reviewed this behavior and explicitly accepted leaving the
  wording/behavior unchanged for now.

## README refresh (2026-04-25)

- Regenerated all four control-window screenshots in `docs/img/` via
  `cache/render_readme_screens.py` to reflect the bright pastel palette.
- Fixed three accuracy gaps in `README.md`:
  - 上部エリア: replaced "ACCEPT / REJECT" pair with the actual layout
    (single ACCEPT toggle + システム終了 button on the top right).
  - ブラウザ UI: replaced obsolete "自分のを止める" wording with the
    real per-kind buttons (画像を消す / 動画を止める / 音声を止める)
    and the all-at-once 自分のぜんぶ取消 button.
  - `config.ini` example: moved `image_display_sec` and
    `media_min_play_sec` into a "Media playback" section, matching the
    real `config.example.ini` layout.

## Mobile UI fixes (2026-04-26)

Two follow-ups in `webpage.py` for the browser-side remote UI; both
verified by headless-Chrome screenshots into `cache/` (the page was
loaded inside fixed-width iframes so media queries actually triggered —
Chrome headless on this host clamps `--window-size` at ~478 px and
ignored a `<meta viewport width=360>` override).

- **FX buttons fit on phones** (commit `7e49e80`).
  Previously the `@media (max-width: 640px)` block forced
  `grid-template-columns: 1fr` with `min-height: 112px`, so the 11 FX
  buttons stacked to ~1230 px tall and required heavy scrolling.
  Restored a 3-column grid with `aspect-ratio: 4/3`, dropped
  `min-height` to 0, clamped font-size to `clamp(12px, 3.4vw, 17px)`,
  and added `white-space: normal; line-height: 1.1;` so the
  `🔴 REC — tap to stop` recording label can wrap inside the narrow
  buttons. Added a `<=360 px` block that drops font further for SE-class
  phones. Also widened the `<=980 px` (tablet) block from 2 to 3
  columns with the same 4:3 ratio.
- **Marquee tag buttons legible on phones** (commit `3e5330b`).
  The single-kanji `赤 / 黄 / 緑 / 水 / 青 / 紫 / 橙 / 白 / 小 / 中 / 大`
  pills rendered at 14 px on near-identical pale pastel backgrounds
  (`#edd7d2`, `#dde9e1`, ...). On a phone the kanji disappeared and the
  buttons looked indistinguishable. Bumped the base
  `.marquee-row button` to `font-size: 15px`, `font-weight: 800`,
  `min-width: 44px`, `padding: 9px 14px`. On `<=640 px` raised to
  16 px / `min-width: 48px` and hid the `.sep` dividers (rows wrap
  instead). Replaced the `.mkp-{r,g,b,y,c,m,w,o}` palette with
  noticeably more saturated tints, gave each tag a matching colored
  border and a darker on-pill text color so the kanji has clear
  contrast on every chip.

### Headless-screenshot recipe used

1. Stub `window.fetch` so the page does not error on `/status`:
   ```js
   window.fetch = async () => ({ok:true, json: async()=>({accept:true, volume:50, mine:{}, me:{}})});
   ```
2. Save the patched HTML as `cache/preview.html`.
3. Embed it in `cache/wrapper.html` inside three fixed-width iframes
   (320 / 360 / 414 px) — the iframe's own width drives the inner
   document's media queries.
4. `chrome --headless --disable-gpu --hide-scrollbars --window-size=1200,2300 --screenshot=...` against the wrapper.
5. Crop the screenshot with PIL to focus on the marquee/FX regions.

## USB MIDI ピアノロール演出 (2026-04-29)

New full-screen演出 driven by a USB-MIDI keyboard.  Selectable from the
control window only; while it is active the host blocks image/video
uploads and renders FX (CHEER 等) translucently on top of the piano roll
so both stay visible.

### New module: `midi_engine.py`

- Wraps `mido` (via `python-rtmidi`) to expose Note-ON / Note-OFF as Qt
  signals (`noteOn(int, int)` and `noteOff(int)`).
- `MidiEngine.is_available()` / `import_error()` are static so the rest
  of the app can degrade cleanly when `mido` isn't installed (the control
  panel shows the import error string and the toggle is still usable —
  just yields no events).
- `mido` callbacks fire on a python-rtmidi worker thread; emitted Qt
  signals queue automatically since the `DisplayWindow` slot lives on
  the main thread.
- Velocity-0 Note-ON is treated as Note-OFF (running-status convention).

### `animations.py` — `PianoRollScene`

- Lifetime: `duration_ms = float("inf")` — the scene is alive for the
  whole time piano-mode is on; `update()` always returns True.  It is
  driven from the same per-frame `_tick` as the FX scenes.
- Layout: 88 keys (MIDI 21..108 = A0..C8), 52 white + 36 black.
  Keyboard occupies the bottom 18 % of the window, roll occupies the
  rest.  Scrolling rate is `scroll_pps` (default 110 px/s, configurable
  via `piano_scroll_pps`).
- Rendering: notes flow UPWARD from the keyboard (live capture style —
  there is no "future" data).  A held note's bottom stays anchored at
  the keyboard top while its top extends upward; on Note-OFF the bar is
  released into the scroll, freezing its height at duration × pps.
- Color is per pitch-class (`note % 12`) so each semitone has a distinct
  hue (C=red, E=yellow, G=cyan, A=blue, etc.).  Held notes get an outer
  glow + matching key color on the keyboard so you can read at a
  glance which key is down.
- Pruning: completed notes whose top edge has scrolled above y=0 are
  dropped each frame to keep `_completed` bounded over long sessions.

### `display_window.py`

- Tracks `_piano_mode: bool` + `_piano_scene: Optional[PianoRollScene]`.
- New signal: `pianoModeChanged(bool)`.
- New slots: `set_piano_mode(bool)`, `piano_note_on(note, vel)`,
  `piano_note_off(note)`, `set_piano_scroll_pps(float)`,
  `set_piano_fx_opacity(float)`.
- `set_piano_mode(True)` clears any image/video background AND creates
  the scene; `set_piano_mode(False)` releases all held notes and drops
  the scene.
- `show_image()` / `play_video()` are no-ops while piano-mode is on
  (`show_image` returns False as before — `_dispatch_play` has a
  separate piano-mode guard above the call so the log line is honest).
- `paintEvent` layering when piano-mode is on:
  1. PianoRollScene fills the frame.
  2. FX scene (if any) drawn at `_piano_fx_opacity` (default 0.55).
  3. Marquee on top.
- `resizeEvent` calls `_piano_scene.resize(w, h)` so the keyboard /
  bars re-layout instantly.

### `web_server.py`

- `WebBridge` gained `set_piano_mode(bool)` / `is_piano_mode()`.
- `/status` JSON now includes `piano_mode: bool` (default false).
- `/upload?type=image` and `/upload?type=video` return 503 with
  `{"reason":"piano_mode"}` while piano-mode is on; audio still goes
  through (it doesn't compete for the canvas).

### `webpage.py`

- `refreshStatus()` reads `j.piano_mode` and calls `updatePianoLock(...)`
  which:
  - Toggles a `.locked` class on the 写真 / 動画 upload labels (greyed,
    `pointer-events:none`).
  - Shows/hides a yellow notice: "🎹 ピアノロール演出中につき、
    写真・動画は現在利用できません。（音声は利用可）".
- The XHR upload path now recognises `{"reason":"piano_mode"}` 503s and
  surfaces "ピアノロール演出中のため現在利用できません" + re-arms the
  lock UI in case the operator just toggled it on.

### `control_window.py`

- New panel inside the 表示 tab: "🎹 ピアノロール (USB MIDI)" with:
  - ON/OFF toggle (forwards to `display.set_piano_mode`).
  - MIDI port `QComboBox` populated from `MidiEngine.list_ports()` +
    `ポート更新` button.  Picking a port opens it; picking
    "(MIDI ポートなし)" closes the current one.
  - Status pill showing `● 演出中 / ○ 停止中` and the open port name.
  - Hint text becomes a yellow warning when `mido` isn't available.
- `display.pianoModeChanged` is connected to `_on_piano_mode_changed`
  which forwards the new state to `bridge.set_piano_mode(...)` so the
  HTTP layer agrees with the on-screen state.
- New log color: `PIANO -> #4a8fc4`.
- `_dispatch_play` short-circuits image/video items with a "再生スキップ"
  PIANO log when piano-mode is on (queue items by other clients no
  longer cause misleading "bad image" logs).
- `_open_image` / `_open_video` (the local file pickers) similarly
  short-circuit when piano-mode is on.

### `pocoboard.py`

- Constructs `MidiEngine` and wires
  `midi.noteOn → display.piano_note_on`,
  `midi.noteOff → display.piano_note_off`.
- Reads `piano_scroll_pps` (default 110) and `piano_fx_opacity_pct`
  (default 55) from `config.ini` and pushes them into the display.
- Closes the MIDI port during shutdown (before `srv.shutdown()`).

### Config / install

- `config.example.ini` gained a "Piano roll (USB MIDI)" section:
  `piano_scroll_pps = 110`, `piano_fx_opacity_pct = 55`.
- `install-deps.bat` now also installs `mido python-rtmidi` (failure to
  install them is non-fatal — the UI just disables the panel and shows
  the import error).

### Verification

- `python -m py_compile midi_engine.py animations.py display_window.py
  control_window.py web_server.py webpage.py pocoboard.py` — clean.
- `cache/test_piano_roll.py` — renders an 88-key keyboard + chord
  progression to `cache/piano_roll_test.png`.  Verifies pitch-class
  coloring, white/black key layout, held-note glow on the keyboard.
- `cache/test_piano_overlay.py` — renders piano roll + CHEER scene at
  opacity 0.55 to `cache/piano_with_cheer.png`.  Confirms the
  semi-transparent stacking spec (両方みえる).
- `cache/test_upload_piano_block.py` — boots a real `WebBridge` HTTP
  server, sends `/upload?type=image|video|audio` while toggling
  `set_piano_mode`, asserts:
  - off: image upload → 200
  - on : image upload → 503 piano_mode
  - on : video upload → 503 piano_mode
  - on : audio upload → 200
  - on : `/status` includes `"piano_mode": true`
- Live boot of `pocoboard.py --no-fullscreen` on this machine (no MIDI
  hardware, no `mido` installed) prints
  `[pocoboard] MIDI: unavailable (ModuleNotFoundError: No module named 'mido')`
  and otherwise starts normally.

## MIDI backend swap → winmm ctypes (2026-04-30)

`mido` + `python-rtmidi` was killed off because the install story was
unworkable in the field:

- The deploy host runs Python 3.14 (Microsoft Store build).
- `python-rtmidi` 1.5.8 is a C++ extension and **has no Python 3.14
  wheel on PyPI**, so pip falls through to building from source via
  meson.
- The host doesn't have Visual Studio (no `cl.exe`, no `vswhere.exe`),
  so meson can't find a C++ compiler and aborts with
  `ERROR: Unknown compiler(s): [['icl'], ['cl'], ...]`.
- The user's `install-deps.bat` therefore failed at the `mido`/`rtmidi`
  step, leaving piano-roll mode without any MIDI input.

POCOBoard targets Windows only, so we now call **`winmm.dll` directly
through `ctypes`** — no third-party Python packages, no compiler, no
deployment step.

### `midi_engine.py` rewrite

- Imports `ctypes` + `wintypes` only; no `mido`, no `rtmidi` references.
- `_bind_winmm()` resolves `winmm.dll` and locks down argtypes/restypes
  for `midiInGetNumDevs`, `midiInGetDevCapsW`, `midiInOpen`,
  `midiInStart`, `midiInStop`, `midiInReset`, `midiInClose`. Setting
  these matters on 64-bit Windows so pointer-sized args (`DWORD_PTR`,
  `HMIDIIN`) don't get truncated to 32 bits.
- `_MIDIINPROC = WINFUNCTYPE(None, c_void_p, c_uint, c_size_t,
  c_size_t, c_size_t)` matches the Win32 callback signature
  `void CALLBACK MidiInProc(HMIDIIN, UINT, DWORD_PTR, DWORD_PTR, DWORD_PTR)`.
  ctypes acquires the GIL on entry, so emitting Qt signals from inside
  the callback is safe.
- The `_cb` ctypes wrapper is held on `self` for the engine's
  lifetime — letting Python GC it would dangle a function pointer in
  winmm and crash on the next event.
- `list_ports()` walks `midiInGetNumDevs()` and uses the Unicode-W
  variant of `midiInGetDevCapsW` so non-ASCII Roland / Yamaha device
  names round-trip correctly.
- `open_port(name)` resolves name → device index, calls `midiInOpen`
  with `CALLBACK_FUNCTION (0x00030000)` then `midiInStart`.
  `close_port()` follows Win32 etiquette: stop → reset → close
  (skipping any of those leaves the device in `MMSYSERR_ALLOCATED` for
  the next reopen attempt).
- `MIM_DATA` short messages have the 3-byte payload packed into
  `dwParam1`'s low 24 bits — split into `status / data1 / data2`,
  treat `0x9X` with vel>0 as Note-On, vel=0 as Note-Off (running
  status), and `0x8X` as Note-Off.  Everything else (CC, pitch bend,
  SysEx, MIM_OPEN/CLOSE/ERROR) is ignored.

### Public API unchanged

`MidiEngine.is_available() / import_error() / list_ports() /
current_port() / open_port() / close_port()` and the Qt signals
(`noteOn(int,int)`, `noteOff(int)`, `portChanged(str)`) all kept the
same shape, so `display_window.py` / `control_window.py` /
`pocoboard.py` did not need any changes beyond the hint text update in
the control panel.

### Install / docs

- `install-deps.bat` no longer attempts to install `mido` or
  `python-rtmidi`.  Only PySide6 is installed.
- The "🎹 ピアノロール (USB MIDI)" panel hint now says "POCOBoard は
  Windows の winmm.dll を直接使うので追加 pip 依存はありません" so the
  operator never sees a stale "pip install mido" instruction.

### Verification

- `python -m py_compile midi_engine.py ...` — clean.
- `MidiEngine.is_available()` returns True on Windows immediately, no
  install needed.
- Boot of `pocoboard.py --no-fullscreen` shows `MIDI ports: (none)` on
  a host with no MIDI hardware (instead of the previous "unavailable
  (ModuleNotFoundError)").  When a USB-MIDI interface is plugged in,
  the same boot line will show its name and the control panel's combo
  populates from `list_ports()`.

## Piano-mode media overlays (2026-04-30)

Piano-roll演出 now lets photos and videos coexist with the keyboard
scene as semi-transparent overlays — uploads are no longer rejected.
This required two structural changes:

### `display_window.py` — QVideoWidget → QVideoSink

`QVideoWidget` rendered straight to the GPU as a child widget, so
`QPainter::setOpacity()` was a no-op for video.  Replaced with
`QVideoSink`:

- `QMediaPlayer.setVideoSink(self._video_sink)` — Qt 6 API.
- `videoFrameChanged(QVideoFrame)` slot stores the latest frame as a
  `QImage` (`frame.toImage()`).  Invalid / empty frames are dropped
  silently so a one-frame decoder hiccup keeps the previous poster
  on screen instead of black-flashing.
- `_draw_video_frame(p, w, h)` letterboxes the latest QImage into the
  full window in `paintEvent`.  Outside piano-mode this draws at full
  opacity (acts as the legacy background).  Inside piano-mode the
  caller wraps it in `setOpacity(self._piano_video_opacity)`.
- `resizeEvent` no longer resizes a child widget; nothing to do.
- `_stop_video_internal` clears `_latest_video_image` so the next
  `play_video()` doesn't briefly flash the prior poster while the
  decoder spins up.

### Layered `paintEvent`

Piano-mode order (back → front):
1. `PianoRollScene.draw()` — opaque base
2. Video frame (if any) @ `_piano_video_opacity` (default 0.35)
3. Image background (if any) @ `_piano_image_opacity` (default 0.35)
   — image / video stay mutex in the visual slot, so at most one of
   2./3. ever paints
4. FX scene @ `_piano_fx_opacity` (default 0.55)
5. Marquee at full opacity

Non-piano-mode order is the legacy behavior, but video is now drawn
in `paintEvent` from `QVideoSink` instead of via a child widget.

### Defaults are deliberately on the lower side (35%)

A bright synthetic test photo at 0.45 was washing out the piano roll
bars (`cache/piano_overlay_full.png` first capture).  At 0.35 the
photo reads as atmosphere while the keys / bars stay dominant — the
scenario the operator actually wants.  Operators with darker photos
can dial it back up via `piano_image_opacity_pct` /
`piano_video_opacity_pct` in `config.ini`.

### Surface changes that fell out

- `web_server.py /upload` — removed the `503 piano_mode` rejection for
  image / video.  `piano_mode` stays in `/status` as informational
  only, so the browser can show a soft hint.
- `webpage.py` — replaced the yellow "現在利用できません" lock note
  with a soft blue "🎹 ピアノロール演出中です。写真／動画は鍵盤の上
  に半透明で重ねて表示されます。" hint, removed the `.locked` CSS,
  and dropped the upload-XHR `piano_mode` 503 path.
- `control_window.py` — `_dispatch_play` no longer skips image / video
  on piano-mode (queue items by remote uploaders fire normally now);
  `_open_image` / `_open_video` (local pickers) likewise.  Hint text
  in the piano panel now says "演出中も写真・動画・エフェクトはそ
  のまま受付され、半透明で重ねて表示されます".
- `set_piano_mode(True)` no longer calls `_clear_image_internal` /
  `_stop_video_internal` — image and video keep playing through the
  toggle.

### Verification

- `python -m py_compile` — clean.
- `cache/test_piano_overlay_full.py` — boots a real `DisplayWindow`,
  enables piano mode, presses 5 chord notes, attaches a synthesized
  test photo via `show_image()`, fires CHEER, posts a marquee, then
  grabs the rendered window.  Resulting screenshot shows all four
  layers visible together: bars + lit keys at the keyboard, photo
  ghosted above, CHEER spotlight cones + confetti overlaid, marquee
  scrolling at the top.

## Piano-mode MIDI stability hardening (2026-04-30, late)

User report: "ノートが表示されない (MIDI を受け取っても何も表示
されない) ので、再起動したら直った". The "restart fixes it"
signature pinned the bug to in-process state; "他は何も変わって
いません" ruled out OS / driver / hardware. Two root-cause classes
fit and both are now defended against.

### 1. Cross-thread signal could race the paintEvent (most likely culprit)

`MidiEngine._on_msg` runs on a winmm worker thread; `noteOn` /
`noteOff` were connected with the default `Qt::AutoConnection`. Auto
re-detects per emit, and *should* always fall through to
`QueuedConnection` here, but if PySide6 ever mis-detected the calling
thread the slot would run on the worker thread itself — modifying
`PianoRollScene._active` concurrently with `paintEvent`'s
`for note, d in self._active.items()` iteration. That throws
`RuntimeError: dictionary changed size during iteration`, which
PySide6 logs to stderr but doesn't propagate, leaving the scene in a
weird state where new note-ons never seem to draw until the app is
restarted (= scene re-built fresh).

Defenses (belt + suspenders + airbag):
- `pocoboard.py` now passes `Qt.ConnectionType.QueuedConnection`
  explicitly on both `midi.noteOn → display.piano_note_on` and
  `midi.noteOff → display.piano_note_off`. No more reliance on Qt
  thread auto-detection for safety-critical paths.
- `display_window.piano_note_on` / `piano_note_off` /
  `_tick → piano_scene.update` wrap the scene call in `try/except` and
  print to stderr on failure. Even if a single bad event blows up,
  the meta-call queue keeps draining and subsequent ticks paint
  normally.
- `PianoRollScene._draw_notes` iterates `list(self._active.items())`
  and `list(self._completed)` instead of the live containers — costs
  nothing and makes any future "callback ran on the wrong thread"
  bug a no-op rather than a freeze.

### 2. Auto-selected MIDI port in the combo wasn't actually opened

`_refresh_midi_ports` (called every time the piano panel mounts and
on every `ポート更新` click) used to do
`self.cbMidiPort.setCurrentIndex(1)` to pre-select the first real
port for the operator's convenience — but `setCurrentIndex` does
NOT fire `activated`, which was the only signal we listened to. So
the combo *displayed* the Roland port name while `midiInOpen` was
never called, and the operator naturally assumed "ポート名出てる →
繋がってる". Pressing piano-mode ON then yielded zero notes; the
restart "fixed" it because the combo + manual click sequence
happened to differ on the second run.

Fixes:
- Connection switched to `currentIndexChanged` (fires for both user
  clicks AND programmatic `setCurrentIndex` outside `blockSignals`).
- `_refresh_midi_ports` now drives `_open_midi_port(target)`
  itself for the auto-select path (the populate is wrapped in
  `blockSignals(True)` so we have explicit control over when open
  fires).
- New `_open_midi_port` helper centralises open + log + combo-rollback
  on failure. `_on_midi_port_picked` now skips when the picked port
  already matches the currently open one — avoids needless close /
  reopen cycles when the operator presses 「ポート更新」 while a
  port is already live.

### 3. Diagnostics so the next failure is loud, not silent

- `MidiEngine.firstNoteSeen` (str) signal — emitted exactly once per
  port-open the first time a note message arrives. The control
  window logs `MIDI 受信開始: <port> から最初のノート` to the PIANO
  channel. Operators (and future agents) can see at a glance whether
  events are flowing.
- `_compose_piano_status` tints the status pill RED with text
  `⚠ MIDI 未接続  ←  下のコンボでポートを選択してください` whenever
  piano-mode is ON but no port is open. Catches the "everything
  ready but nothing happens" trap visually.
- `MidiEngine.portChanged` is now wired into `_refresh_piano_status`
  so the pill stays in sync if anything else opens / closes the port.

### Verification

- `python -m py_compile` — clean.
- `cache/test_midi_stability.py` queues ~1300 random
  `piano_note_on` / `piano_note_off` invocations from a worker
  thread (via `QMetaObject.invokeMethod`
  + `Qt.ConnectionType.QueuedConnection`) over 2 s while the Qt
  event loop drains them. End state: 940 on / 350 off processed,
  scene `_active`=63 / `_completed`=877, no crash, no exception
  printed. Confirms the defensive `list()` snapshot + try/except
  hold up under real concurrency.

