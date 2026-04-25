# Agent Handoff

Updated: 2026-04-26 (mobile UI fit + marquee tag legibility)

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
