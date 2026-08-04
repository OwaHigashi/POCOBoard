# Agent Handoff

Updated: 2026-08-05 (stretch-mode camera fill + piano roll over camera)

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

## Marquee size scale (2026-05-10)

User report: ニコニコ風スクロール文字が小さすぎて配信視聴者から
読めない。全体に 1.5 倍くらい大きくしたい + 管理画面から自由に
スケール変更したい (50〜500%)。

### `marquee.py`

- `MarqueeEngine` gained a global `scale: float` (default 1.0).
  Both `_font_at` and `_lane_height` now multiply pixel size by
  `self.scale` so per-message `<small>/<big>` tags stack on top of
  the operator-set baseline instead of being capped by it.
- New `set_scale(float)` method clamps to `>= 0.1` and **clears
  `self.tracks`** on a real change.  The reason: each `_LaidRun`
  caches its own `width / ascent / descent` from the metrics at
  layout time.  If we only flip the scale and let in-flight tracks
  keep scrolling, `_draw_runs` paints text at the new size while
  `cursor_x += r.width` advances by the old width — visually that
  shows up as overlap or runaway gaps.  Wiping the in-flight set
  is cheap and matches the operator's mental model ("change size,
  start fresh").
- The `_metrics_cache` key is `(family, pixelSize, weight)`, so
  scale changes simply produce new cache entries.  No invalidation
  needed; the cache stays bounded as long as the operator doesn't
  spam every percent step.

### `display_window.py`

- New `Slot(float) set_marquee_scale(scale)` forwards to
  `MarqueeEngine.set_scale`, then `_emit_marquee_status()` (the
  cleared track count goes to 0) and `update()`.

### `pocoboard.py`

- Reads `marquee_size_pct` from config (default **150**).  Clamped
  to 50..500 before being applied as `scale = pct / 100` so a
  malformed config can't make the engine emit 0-pixel fonts or
  pathological sizes.
- 150 % is the new shipped default — the user's original "全体に
  5割大きく" request — so the on-screen text is comfortably
  readable for the audience without any operator action.

### `control_window.py`

- 横スクロール tab: new `QSpinBox` `文字サイズ:` next to the
  speed combo, range 50..500, step 10, suffix " %".  Initial value
  reads `display._marquee.scale * 100`, so it picks up whatever
  the config / earlier session left in place.
- `valueChanged` → `display.set_marquee_scale(v / 100.0)` and
  logs an `ADMIN` line so changes show up in the log tab.
- Tooltip warns that changing size clears in-flight messages.
- Bottom hint mentions the new 50%–500% range.

### Config

- `config.example.ini`: added `marquee_size_pct = 150` with a
  short comment describing the live override.
- `README.md`: 横スクロールタブ section gained the 文字サイズ
  bullet + the "changing size clears in-flight messages" note;
  the sample config block now lists `marquee_size_pct = 150`.

### Verification

- `python -m py_compile marquee.py display_window.py
  control_window.py pocoboard.py` — clean.
- No live-render verification was performed (host has no display
  window open during this session).  Smoke check on next boot:
  start POCOBoard, flow a message, confirm it renders ~1.5x the
  pre-change size by default, then drag the spinbox to 250 % and
  500 % to confirm scale + auto-clear behavior.

## Split FX / external volume (2026-08-04)

User report: リスナー由来の音 (TALK・アップロード音声・動画) が小さい
のでボリュームを上げると、アイテム効果音 (BOMB/CHEER 等) が大き
すぎてびっくりする。単一の音量スライダでは両者のバランスが取れない
ので、別々に調整できるようにした。

### Volume grouping

Two independent gains replace the single master:

- **効果音 (FX)** — synthesized one-shots (bomb/cheer/hearts/...).
- **外部音声 (external)** — TALK mixer sink + uploaded audio files
  (`QMediaPlayer`/`QAudioOutput` file player) + **video sound**
  (`DisplayWindow._video_audio`, which was previously hard-coded at
  0.8 and not connected to any slider at all).

### Code changes

- `audio.py`
  - `_volume` → `_fx_volume` + `_ext_volume` (both default 0.8).
  - New `set_fx_volume(int)` (fx sink) and `set_ext_volume(int)`
    (talk sink + file output).  `set_volume(int)` kept as a legacy
    master that sets both — nothing in-tree calls it anymore but it
    keeps external callers / old scripts working.
  - `play_fx`, `_build_talk_sink`, `_ensure_file_player` each apply
    their group's gain.
- `display_window.py`
  - New `_video_volume` (default 0.8) + `Slot(float)
    set_video_volume(vol)`; applied in `_ensure_video_player` and
    live to an existing `_video_audio`.
- `control_window.py`
  - 音量 group box now holds two labeled sliders (QGridLayout):
    `効果音` → `audio.set_fx_volume`; `外部音声` →
    `audio.set_ext_volume` + `display.set_video_volume` +
    `bridge.set_volume` (the browser /status `volume` pill now
    reflects the *external* gain — that's the one governing how loud
    a listener's own content plays).
  - `set_initial_volume(v)` → `set_initial_volumes(fx, ext)`.
- `pocoboard.py`
  - New config keys `startup_fx_volume` / `startup_ext_volume`,
    both defaulting to the existing `startup_volume` (old config.ini
    keeps its previous behavior).  Wires bridge + audio + display
    video volume + control sliders from them.
- `config.example.ini` / `README.md` — documented the two keys and
  the two-slider 音量 UI.

### Verification

- `python -m py_compile audio.py display_window.py
  control_window.py pocoboard.py` — clean.
- Live smoke test (scratchpad, real `AudioEngine` under
  `QCoreApplication` on this host): talk sink volume follows
  `set_ext_volume` (0.90), lazily-created file output picks up the
  ext gain (0.70), legacy `set_volume` still drives both groups,
  0..100 clamping holds.
- Not verified live: actual audible balance on the deploy rig (needs
  real TALK input + FX side by side), and the control-window layout
  render (no GUI session here).  Next boot: check the 音量 box shows
  two sliders and that dragging 外部音声 changes video sound too.

## Live camera default mode (2026-08-04)

User request: USB カメラや仮想カメラ (OBS 等) の映像を画面に表示する
機能。これが表示されているモードがデフォルト。カメラ表示中は効果
(FX) や飛ぶ文字 (マーキー) を半透明で重ね、その不透明度も調整可能に。
追加要件: カメラ映像から狙った場所を 9:16 (720x1280) で crop して
縦型表示。縦横比は絶対に変えない（X/Y 同率スケール）。

### Architecture

`QCamera + QMediaCaptureSession + QVideoSink` (Qt6) — frames land as
QImage in `_latest_camera_image`, drawn in paintEvent like the video
path.  Virtual cameras (OBS Virtual Camera 等) appear in
`QMediaDevices.videoInputs()` on Windows like any USB cam.

Visual stack priority (back → front base layer):
piano roll > uploaded video > uploaded image > **camera feed** > idle
title > black.  I.e. the camera is the *idle background*: uploads still
take the screen as before, and when they end/clear the display falls
back to the camera instead of the POCOBOARD title.  `camera_visible`
in paintEvent = camera mode on AND frame present AND no image/video AND
not piano mode.

While `camera_visible`:
- FX scenes draw at `_camera_fx_opacity` (default 0.55)
- Marquee draws at `_camera_marquee_opacity` (default 0.75)
Both live-tunable 0..100 % from the control window; over video the
legacy fixed 0.75 FX opacity is unchanged, and piano mode keeps its own
opacities.

### Portrait 9:16 crop (720x1280)

`_draw_camera_frame`: source rect = largest 9:16 window fitting the
frame (`crop_h = min(ih, iw*16/9) / zoom`, `crop_w = crop_h*9/16`),
centered on aim point (`_camera_crop_cx/cy`, fraction 0..1, clamped so
the window stays inside the frame).  Dest rect = 720x1280-proportioned
rect fitted+centered in the window (`scale = min(w/720, h/1280)`).
Source and dest share the exact 9:16 aspect → `drawImage` scales X and
Y identically, aspect never distorts.  `set_camera_portrait(False)`
falls back to full-frame letterbox (shares `_draw_letterboxed` helper
with the video path now).

### Files

- `display_window.py` — camera state + `set_camera_mode/device/
  fx_opacity/marquee_opacity/portrait/crop_cx/crop_cy/crop_zoom`,
  `_start_camera/_stop_camera/_on_camera_frame/_on_camera_error`,
  `_resolve_camera_device` (id exact → description substring → default),
  paintEvent layering above.  Camera keeps running while hidden behind
  uploads (instant return, no re-open lag).
- `control_window.py` — new 📷 カメラ表示 box in 表示 tab (above the
  piano box): ON/OFF toggle, device combo + カメラ更新 (auto-selects
  via currentIndexChanged — same "programmatic select must actually
  open" lesson as the MIDI combo), 効果の濃さ / 文字の濃さ spinboxes,
  縦型 9:16 クロップ checkbox + 位置X / 位置Y / ズーム spinboxes.
  Reads initial state from display (pocoboard configures display before
  ControlWindow is constructed).
- `pocoboard.py` — config keys `camera_on_boot` (default **true** =
  camera is the shipped default mode), `camera_device` (empty=default,
  else id/description match), `camera_fx_opacity_pct` (55),
  `camera_marquee_opacity_pct` (75), `camera_portrait_crop` (true),
  `camera_crop_cx_pct`/`cy_pct` (50), `camera_crop_zoom_pct` (100,
  clamped 100..800).  Camera stopped on shutdown before MIDI close.
- `config.example.ini` / `README.md` — documented.

### Verification

- `py_compile` clean.
- Offscreen render test (scratchpad `test_camera_overlay.py`): real
  DisplayWindow + synthetic 4-quadrant camera frame injected directly.
  Verified: center crop shows red|green split with black pillarbox,
  aim (0.75,0.75)+2x zoom shows solid yellow, CHEER over camera keeps
  picture visible (#8e7e26 blend), setter clamping, full-frame
  letterbox fallback.
- Live boot on this host (offscreen, port 8099): prints
  `[camera] started: Live Streamer CAM 313` (real USB cam auto-started
  by default) and the control window builds cleanly.
- Not verified: on-screen look with a real camera (this session was
  offscreen), device hot-unplug while running (QCamera errorOccurred
  just logs; feed freezes on last frame until操作), OBS virtual camera
  enumeration on the deploy host.

## Performance pass (2026-08-04)

Whole-app review for CPU waste; boot-time FX synthesis was measured at
0.56 s total and left alone (disk-caching it isn't worth the
complexity).  Changes, highest impact first:

### 1. Conditional repaint (display_window.py)

`_tick` used to call `self.update()` unconditionally at 60 fps —
full-window repaints forever, even on a static idle screen.  Now it
repaints only when:
- an animation is live (`_scene`, `_piano_scene`, marquee tracks,
  title fade in progress), or
- a new camera/video frame arrived (`_frame_dirty`, set by the two
  sink callbacks), or
- a state-changing slot marked `_dirty` (set in `_mark_activity`,
  stop_marquee, image/video clear paths, clear_display, camera
  crop/opacity/portrait setters; scene-death and last-marquee-gone
  transitions set it inside `_tick` so the final erase frame paints).

Fallback: a ~2 Hz heartbeat repaint when idle, so the tiny status
footer stays fresh and ANY missed invalidation self-heals within
500 ms — that's the safety net that makes the gating low-risk.  Idle
= 2 paints/s (was 60); camera mode = capture rate (~30).

**Rule for future slots**: any new visual-state mutation must either
set `self._dirty = True` or call `self.update()` directly; worst case
the heartbeat covers you for half a second.

### 2. Frame/photo scaling caches (display_window.py)

- `_cached_frame_pixmap(img, crop, dw, dh)` — single-slot cache keyed
  on `QImage.cacheKey()` + crop + size.  Camera portrait crop, camera
  letterbox, and video letterbox all go through it: the crop / scale /
  QImage→QPixmap conversion now happens once per *frame* (~30 fps)
  instead of once per *paint* (60 fps when marquee/FX overlay).
  Invalidation is automatic (cacheKey changes per frame); cleared on
  video stop / camera stop for memory hygiene.
- `_draw_bg_image` caches the letterboxed photo scaled to screen size
  (`_bg_cache_*`), now with SmoothTransformation — the old code
  fast-rescaled the full-resolution pixmap on every single paint; the
  new one smooth-scales once per (photo, size) and blits.  Better
  quality AND ~free repaints.

### 3. Hidden-camera conversion skip (display_window.py)

`_on_camera_frame` returns before `frame.toImage()` while the camera
is occluded (piano mode / video / image showing).  The feed stays
open; visibility returns within one capture frame.  Saves a constant
~30 fps full-frame conversion during uploads and piano sessions.

### 4. TALK resample fast path (audio.py)

`_resample_int16le` decimates via `array[::step]` when
`src_sr % dst_sr == 0` (the 48000→16000 case browsers actually
produce when they ignore the 16 kHz AudioContext hint).  Measured
0.006 ms vs 0.528 ms per 200 ms chunk (~90x) — this runs on the Qt
main thread per received TALK chunk, so it directly reduces UI-thread
load with many talkers.  Non-integer ratios keep the linear-interp
loop.  Neither path filters (unchanged behavior).

### 5. Single-speaker mixer fast path (audio.py)

`_pump` now collects ready chunks first; with exactly one active
stream (the overwhelmingly common case) the chunk is written as-is
(zero-padded to 640 B) — no unpack, no accumulate, no clip, no
re-pack.  ≥2 speakers use the original mix+saturate path over the
collected chunks.  Silence keep-warm chunk is a module constant
(`_TALK_SILENCE`) instead of a per-tick allocation.

### 6. Marquee micro-opts (marquee.py / display_window.py)

- `_font_at` caches QFont per size_scale (was: fresh QFont per run
  per painted frame).  Cache cleared in `set_scale` with the tracks.
- `marqueeStatusChanged` emits only when (used, max) actually changes
  (was: every tick while anything scrolled → 60 Hz signal + locked
  bridge write).

### Verification

- `py_compile` all touched modules — clean.
- `test_perf_changes.py` (scratchpad): 48k→16k fast path bit-exact vs
  decimation reference, non-integer path length check, passthrough
  identity; real-AudioEngine pump exercised through both the
  single-speaker and 2-speaker paths.
- `test_repaint_gate.py` (scratchpad): real DisplayWindow with
  hand-driven `_tick` — 20 idle ticks → 0 repaints, heartbeat fires
  at 500 ms, dirty→exactly one repaint, camera frame→repaint, FX→
  repaint every tick, marquee→repaints, status signal emits once for
  repeated identical values.
- Camera overlay render test + split-volume test re-run — still green.
- Live offscreen boot — clean, camera auto-starts.
- Not measured on real hardware: actual CPU% delta on the deploy rig
  (offscreen host lacks RHI; the paint savings should be larger with
  a real 4K display window).

## DirectShow backend for ManyCam / OBS virtual cameras (2026-08-05)

User report: USB カメラは認識するが ManyCam の出力が認識されない。

### Root cause (verified on this host, Windows 11 build 26200)

Qt 6 enumerates cameras via **Windows Media Foundation**, which only
sees modern camera-category devices.  Probing this machine:
- `QMediaDevices.videoInputs()` → 1 device (Live Streamer CAM 313)
- DirectShow `ICreateDevEnum` → **5 devices**: the USB cam plus
  ManyCam Virtual Webcam (driver-based, PnP class "Image"),
  OBS Virtual Camera, NVIDIA Broadcast, Insta360 Virtual Camera.
Driver/filter-based virtual webcams register only the legacy
DirectShow/KS categories → invisible to MF/Qt by design.

### Second discovery: SampleGrabber is dead on new Windows 11

The classic DShow capture recipe (qedit.dll SampleGrabber +
NullRenderer) NO LONGER WORKS on this build: qedit.dll ships but the
classes are gone — CoCreateInstance → REGDB_E_CLASSNOTREG, and direct
`DllGetClassObject` → CLASS_E_CLASSNOTAVAILABLE.  Do not resurrect
that path.  Instead frames are pulled through a **windowless VMR9**
(quartz.dll — same DLL as FilterGraph, cannot be absent):
graph = source → VMR9(windowless, clipping hwnd = hidden 16x16
QWidget with WA_DontShowOnScreen), poll
`IVMRWindowlessControl9::GetCurrentImage` (packed 32bpp bottom-up DIB
in CoTaskMem → QImage Format_RGB32 + vertical flip).  Verified: frame
delivery CONTINUES with the hwnd hidden (checked frames differ over
time with the real USB cam through this path), first frame ~50 ms,
grab cost ~1 ms @480p / ~10 ms @1080p.

### New module `dshow_camera.py` (pure ctypes COM, no pip deps)

- `list_dshow_cameras()` → [(moniker_display_name, friendly_name)].
  Moniker display name (`@device:pnp:...` / `@device:sw:...`) is the
  stable unique id.
- `DShowCamera.open(moniker_name)` / `grab() -> QImage | None` /
  `close()`.  GUI-thread only (owns the hidden QWidget; COM STA).
- All vtable slot indices are hand-counted and commented per call —
  when editing, recount against the SDK headers; a wrong slot fails
  silently or corrupts (the enum prototype originally called
  ComposeWith instead of BindToStorage — symptom was "5 devices, all
  names unreadable").

### `display_window.py` integration

- `available_cameras()` static → union [(ident, desc, backend)]:
  Qt/MF devices first, then DShow-only ones (deduped by
  case-insensitive name — same physical device appears in both).
- `_camera_backend: 'qt'|'dshow'` + `_dshow_cam/_dshow_ident/_desc`.
  `set_camera_device` resolves across the union (exact id →
  description substring, Qt preferred); `current_camera_id/
  description` are backend-aware; `_start_camera` dispatches, and
  falls back to a DShow device if NO MF camera exists at all.
- DShow is pull-based: `_tick` polls `grab()` every ≥33 ms, only
  while camera is visible (same occlusion rule as the Qt sink skip)
  → sets `_latest_camera_image` + `_frame_dirty`.  Everything
  downstream (portrait crop, opacities, caches) is backend-agnostic.
- `_stop_camera` closes the DShow graph too.

### `control_window.py`

Camera combo now lists `display.available_cameras()` (union) —
QMediaDevices import dropped.  No UI shape change.

### Verification

- Standalone: ManyCam enumerated + opened, 1920x1080 "Please start
  ManyCam" placeholder frame captured and visually confirmed (PNG),
  30/30 sustained grabs, clean close.  Liveness proven via USB cam
  through the same path (frames differ over 0.5 s).
- End-to-end: DisplayWindow resolves "ManyCam" substring → dshow
  backend, tick-poll delivers frames, full render (portrait crop
  pipeline) shows ManyCam's background color at center, mode-off
  releases the graph, switching back to "Live Streamer" flips to the
  qt backend.
- Regressions green: camera overlay render test, repaint-gate test.
  Live boot unchanged (default = USB cam via Qt path).
- Note: ManyCam placeholder ("Please start ManyCam") is what the
  virtual cam outputs when the ManyCam app is closed — expected.
- Not verified: behavior when ManyCam app starts/stops WHILE POCOBoard
  is capturing (likely fine — the driver keeps streaming), long-run
  stability of GetCurrentImage polling (~10 ms/frame @1080p on the
  GUI thread; if it ever matters, decimate to 15 fps or move to a
  worker thread).

## Per-device portrait-crop policy (2026-08-05)

User report: ManyCam の映像が POCOBoard 側で左右が切れて細くなる。
Cause: the 9:16 portrait crop (built for aiming a RAW USB camera at a
phone) was slicing a ~607px-wide vertical strip out of ManyCam's
already-composed 1920x1080 output.  The user worked around it by
unchecking 縦型クロップ; this change makes that automatic.

- `display_window.py`: effective crop mode is now computed per device:
  **explicit operator choice (remembered per camera ident in
  `_camera_crop_pref`, session-only) > backend default** — dshow
  (virtual cams: ManyCam / OBS / NVIDIA Broadcast) → full frame;
  qt (physical cams) → `_camera_portrait_default` from config.
  `set_camera_portrait()` (UI checkbox) records the per-device pref;
  new `set_camera_portrait_default()` is what pocoboard.py feeds from
  `camera_portrait_crop`.  `_apply_camera_crop_pref()` runs on every
  device selection incl. the auto-resolve fallbacks in _start_camera.
- `control_window.py`: `_sync_camera_portrait_checkbox()` (blockSignals
  so syncing isn't recorded as an operator choice) after device pick /
  list refresh.
- Crop position/zoom (位置X/Y・ズーム) stay global, only ON/OFF is
  per-device — revisit if an operator actually needs per-device aim.
- Verified: ManyCam select → crop OFF, USB cam → ON (config),
  overrides remembered independently per device across switches;
  camera-overlay regression green; live boot green.

## Anamorphic portrait corrections (2026-08-05)

User setup: a capture board reports 1920x1080 but the real picture is
portrait 1080x1920 squeezed into that frame (looks つぶれて).  Their
mental model, implemented literally: compose the base screen at
1080x1920 proportions, stretch it to 1920x1080 on output, and the
downstream chain's squeeze restores true proportions.  Follow-up
requirement: 「全ての描画をこの引き延ばしに対応する必要があります」 —
EVERY layer, not just the camera, must go through the stretch.

Two independent, composable features:

### 1. Camera ingest un-squeeze (per-device) — `縦横補正`

- `display_window.py`: `_ingest_camera_frame(img)` is now the single
  ingest point for BOTH camera backends (Qt sink callback + dshow
  tick-poll).  When `_camera_swap_aspect` is on it restretches the
  frame to its transposed size (1920x1080 → 1080x1920,
  IgnoreAspectRatio on purpose — the non-uniform scale IS the fix);
  corners stay corners (no rotation).
- Preference model identical to the portrait crop: per-device operator
  memory (`_camera_swap_pref`) > config default
  (`camera_swap_aspect`, default false) via `set_camera_swap_aspect` /
  `set_camera_swap_default`, recomputed in `_apply_camera_crop_pref`
  on device switches.
- UI: `縦横補正` checkbox in the camera box crop row; synced (without
  recording a pref) by `_sync_camera_portrait_checkbox`.

### 2. Whole-output portrait stretch (global) — `縦型出力補正`

- `display_window.py`: `_virtual_size()` returns the composition size
  — (w, h) normally, transposed (h, w) when `_output_stretch` is on.
  paintEvent applies `p.scale(width/vw, height/vh)` and every layer
  below just draws into the virtual (w, h); the transform stretches
  the finished composition onto the physical window.  All layout
  entry points now use `_virtual_size()`: `trigger_fx` (make_scene),
  `add_marquee`, `set_piano_mode` (PianoRollScene), `resizeEvent`.
- `set_output_stretch(on)` clears in-flight marquee tracks (laid out
  against the old geometry — same policy as marquee size changes) and
  resizes the piano scene.
- Config `display_portrait_stretch` (default false); live checkbox in
  the 表示 tab (row 4, above the media hint; camera box moved to row
  6, piano 7, stretch row 8).
- Note the two features compose: capture-board camera (squeezed
  portrait) + portrait output chain wants BOTH — swap makes the frame
  truly 9:16, which then letterboxes full-bleed into the 9:16 virtual
  canvas, and the output stretch maps it onto the 16:9 signal.

### Verification

- Offscreen test (`test_stretch.py`): ingest swap produces 1080x1920
  with corners preserved; with swap+stretch a squeezed 4-quadrant
  frame fills the whole 1600x900 window (all four quadrants at the
  window corners — nothing cut); CHEER FX and a marquee render under
  the transform without error; stretch-off restores the normal canvas;
  per-device swap memory independent of the crop pref.
- Regressions green: camera overlay, crop policy, repaint gate.
  Live boot green.
- Not verified on real hardware: the actual capture-board chain and
  the physically-portrait output display (needs the deploy rig).
  Fonts/AA under the non-uniform transform look fine in offscreen
  grabs but deserve an eyeball on the real 4K output.

## Next session pickup (2026-08-05, session closed)

State: everything through commit `9cef131` is pushed to
github.com/OwaHigashi/POCOBoard main (incl. the stretch-mode camera
full-bleed + translucent piano roll — see the section further below).
Working tree clean.  No code in flight, no half-finished refactors.

### What shipped in the 2026-08-04..05 sessions (all pushed)

1. `9506032` — split FX / external volume (2 sliders) + camera default
   mode with portrait 9:16 crop + piano/marquee overlay opacities.
2. `42301ac` — performance pass: conditional repaint (idle 60fps→2Hz
   heartbeat), frame/photo scaling caches, occluded-camera conversion
   skip, TALK resample fast path (~90x), single-speaker mixer fast
   path, marquee font cache + status-signal throttle.
3. `ca243c9` — `dshow_camera.py`: DirectShow backend (ctypes COM,
   VMR9 windowless + GetCurrentImage polling) so ManyCam / OBS
   virtual cameras appear and capture; unified camera list.
4. `b8f18aa` — per-device crop policy: virtual cams default to
   full-frame, per-device ON/OFF memory (session-only).
5. `aa5f5eb` — anamorphic corrections: per-camera 縦横補正 (ingest
   un-squeeze, `camera_swap_aspect`) + global 縦型出力補正
   (whole-screen 9:16 compose → 16:9 stretch,
   `display_portrait_stretch`).

### User-confirmed working

- ManyCam is now recognized and, after the per-device crop default,
  displays full-width (user confirmed the crop was the cause).

### Awaiting real-rig verification (top of next session)

1. **Capture-board portrait chain** — first attempt (`aa5f5eb`)
   letterboxed the camera and the user reported "更に細くなった";
   fixed in `9cef131` (camera full-bleed in stretch mode).  User
   should re-test 縦型出力補正 on the rig: camera should now fill the
   output and return to true proportions downstream.  If the
   direction is STILL wrong, combine with per-camera 縦横補正; an
   inverted output transform was considered and rejected (see the
   9cef131 section).  Also eyeball FX / marquee text quality under
   the non-uniform stretch; if AA looks bad, consider compositing
   into an offscreen portrait QImage instead of the painter-scale
   approach.
2. **Piano roll over camera** (`9cef131`) — verify on the rig that
   the roll at 65 % keeps both the camera and the notes readable;
   tune via 「カメラ表示中のロールの濃さ」.
3. Volume balance (効果音 vs 外部音声 sliders) with real TALK + FX
   side by side.
4. Long-run stability of dshow GetCurrentImage polling (~10 ms/frame
   @1080p on the GUI thread) and ManyCam app start/stop while
   POCOBoard is capturing.

### Open design notes / possible next steps

- Crop/swap per-device memory is session-only; persist to config or a
  small state file if the operator asks.
- Crop position/zoom (位置X/Y・ズーム) are still global, not
  per-device.
- 縦型出力補正 + 縦型9:16クロップ both on means the portrait camera
  fills the portrait canvas — correct, but zoom/aim still apply; check
  operator expectations on the rig.
- If dshow polling cost ever matters: decimate to 15 fps or move the
  grab to a worker thread.

## Stretch-mode camera fill + translucent piano roll (2026-08-05, later)

User feedback on the rig: pressing 縦型出力補正 made the camera
picture EVEN NARROWER ("更に細くなりました…逆に設計してください"),
and piano-roll mode made the camera video disappear entirely
("ピアノロール画面自体が、半透明にならないとダメです").

### 1. Camera full-bleed in output-stretch mode

Root cause of the "narrower" complaint was NOT an inverted transform:
the camera frame (16:9-tagged) was being LETTERBOXED into the 9:16
virtual canvas → a thin horizontal band that the stretch then squashed
further.  The camera signal comes from the same anamorphic chain as
our output, so in stretch mode it must be passed through FULL-BLEED:
`_draw_camera_frame` now fills the whole virtual canvas
(no letterbox) when `_output_stretch` is on and the portrait crop is
off.  Net effect: camera = identity through POCOBoard, downstream
squeeze restores it; FX/marquee still get the pre-distortion.
With 縦横補正 (swap) also on, the frame is truly 9:16 = same fill,
aspect-preserving.  Photos/videos keep letterboxing (they carry real
aspect ratios).

If the rig STILL shows the wrong direction after this, the remaining
lever is the per-camera 縦横補正 checkbox; a genuinely inverted
output transform (compose ultra-wide, squeeze) was considered and
rejected — no realistic chain maps to it.

### 2. Piano roll translucent over the camera

- Piano mode no longer occludes the camera: the ingest skip
  (`_on_camera_frame`) and the dshow tick-poll now only skip for
  video/image uploads.
- paintEvent piano branch: when a camera frame is available, draw
  camera as the opaque base, then the PianoRollScene at
  `_piano_roll_opacity` (default 0.65); without a camera the roll
  paints opaque exactly as before.
- New `set_piano_roll_opacity`, config `piano_roll_opacity_pct = 65`,
  spinbox 「カメラ表示中のロールの濃さ」 in the piano panel (row 2;
  hint moved to row 3).

### Verification

- Offscreen: stretch mode + 4-quadrant camera frame → fills the
  entire window incl. top edge (no letterbox band); piano roll over
  camera shows red/green tint through the roll (L=#5f080d R=#05620d
  at 65%), opacity 100% hides more; Qt-sink ingest continues during
  piano mode (fake-frame test); no-camera piano path renders opaque.
- Regressions green: test_stretch, camera overlay, crop policy.
  Live boot green.
- Not verified on the rig: the actual capture-board chain with the
  new fill behavior — next real-hardware check.

