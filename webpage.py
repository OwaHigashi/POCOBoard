"""HTML/CSS/JS served at `/` for browser remote control.

Mirrors M5Tab-Poco's UX: BOMB / CHEER / TALK big buttons, marquee composer
with color/size/underline/highlight tags, x1..x5 speed, send/stop, overflow
(<sp>) hidden button.  Tailored for Windows hosts: no external CDN audio
(host plays its own sounds), so everything works on LAN without internet.
"""

INDEX_HTML = r"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>POCOBoard Remote</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html,body { margin:0; padding:0; min-height:100%; background:#0a0a0f; color:#eee;
              font-family: -apple-system, "Segoe UI", "Hiragino Sans", "Noto Sans JP", sans-serif; }
  header { padding: 14px 20px; display:flex; justify-content:space-between; align-items:center;
           background: linear-gradient(90deg, #111, #222); border-bottom: 1px solid #333;
           position: sticky; top:0; z-index:100; gap:12px; flex-wrap:wrap; }
  #who input:focus { outline: 2px solid #3a8fff; border-color:#3a8fff; }
  header h1 { margin:0; font-size:22px; letter-spacing:2px; }
  #status { font-size: 13px; opacity:.85; }
  .pill { display:inline-block; padding:3px 10px; border-radius:999px; background:#333; margin-left:6px; }
  .on  { background:#1b7f3a; }
  .off { background:#b22525; }
  main { display:grid; grid-template-columns: repeat(3, 1fr); gap:14px; padding:18px; }
  button.fx {
    position:relative; overflow:hidden; border:none; border-radius: 18px;
    aspect-ratio: 3 / 2; font-size: clamp(20px, 4vw, 36px); font-weight: 900;
    color:#fff; cursor:pointer; letter-spacing: 3px;
    transition: transform .08s ease, box-shadow .2s ease;
    box-shadow: 0 6px 20px rgba(0,0,0,.6), inset 0 0 40px rgba(255,255,255,.10);
  }
  button.fx:active { transform: scale(.97); }
  button.fx[disabled] { opacity:.35; cursor:not-allowed; }
  .bomb   { background: radial-gradient(circle at 30% 30%, #ff6a00, #8a0303 60%, #200 100%); }
  .clap   { background: radial-gradient(circle at 30% 30%, #ffe066, #ff3ea5 50%, #5a00a0 100%); }
  .talk   { background: radial-gradient(circle at 30% 30%, #3ee8ff, #0066aa 50%, #002040 100%); }
  .hearts { background: radial-gradient(circle at 30% 30%, #ff9ac1, #ff3355 55%, #660022 100%); }
  .stars  { background: radial-gradient(circle at 30% 30%, #ffffaa, #ff9900 50%, #662200 100%); }
  .snow   { background: radial-gradient(circle at 30% 30%, #ffffff, #88ccff 50%, #003366 100%); color:#001133; text-shadow:0 0 4px #fff; }
  .talk.recording {
    background: radial-gradient(circle at 30% 30%, #ff6a6a, #a00000 50%, #300 100%);
    animation: rec-pulse 1s ease-in-out infinite;
  }
  @keyframes rec-pulse {
    0%,100% { box-shadow: 0 8px 28px rgba(255,0,0,.4), inset 0 0 60px rgba(255,255,255,.08); }
    50%     { box-shadow: 0 8px 48px rgba(255,0,0,.95), inset 0 0 80px rgba(255,255,255,.15); }
  }
  .marquee-box { grid-column: 1 / -1; display: grid; gap: 8px;
                 padding: 14px; border-radius: 18px; margin-top: 4px;
                 background: linear-gradient(135deg, #1b1b24, #23103a);
                 box-shadow: 0 8px 28px rgba(0,0,0,.6); }
  .marquee-box textarea { width: 100%; min-height: 72px; resize: vertical;
                          padding: 12px; border-radius: 10px;
                          border: 1px solid #444; background: #0a0a0f;
                          color: #eee; font-size: 16px;
                          font-family: inherit; }
  .marquee-row { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
  .marquee-row button { padding: 6px 10px; border-radius: 6px;
                        border: 1px solid #555; background: #222;
                        color: #fff; cursor: pointer; font-weight: 700;
                        font-size: 14px; min-width: 36px; line-height: 1.2; }
  .marquee-row button.send { background: #1b7f3a; border-color: #2a9a4a; padding: 6px 14px; }
  .marquee-row button.stop { background: #7f1b1b; border-color: #9a2a2a; padding: 6px 14px; }
  .marquee-row .sep { width:1px; height:24px; background:#444; margin:0 4px; }
  .mkp-speed.on { background: #0a66aa !important; border-color:#1a8acc !important; }
  .mkp-speed.on::after { content:' *'; }
  .mkp-r { background:#7a1a1a !important; }
  .mkp-g { background:#1a7a1a !important; }
  .mkp-b { background:#1a1a7a !important; }
  .mkp-y { background:#7a7a1a !important; }
  .mkp-c { background:#1a7a7a !important; }
  .mkp-m { background:#7a1a7a !important; }
  .mkp-w { background:#555   !important; }
  .mkp-o { background:#b55a00 !important; }
  .mkp-sz { background:#2d2d40 !important; }
  .mkp-u  { background:#333    !important; text-decoration: underline; }
  .mkp-hl { background:#222    !important; box-shadow: inset 0 0 0 2px #888; }
  .marquee-row .spd { margin-left: auto; display:flex; gap:4px; align-items:center; }
  .marquee-row .spd label { font-size:13px; opacity:.75; }
  #mqCount { font-size:13px; opacity:.7; }
  .upload-box { grid-column: 1 / -1; display: grid; gap: 8px;
                padding: 14px; border-radius: 18px; margin-top: 4px;
                background: linear-gradient(135deg, #1b241b, #0f2a18);
                box-shadow: 0 8px 28px rgba(0,0,0,.6); }
  .upload-row { display: flex; gap: 10px; flex-wrap: wrap; }
  .upload-btn { flex: 1 1 160px; text-align:center; padding: 14px 10px;
                border-radius: 12px; cursor: pointer; font-weight: 800;
                font-size: 16px; letter-spacing: 1px; color:#fff;
                border: 1px solid #3a5a3a; transition: transform .08s ease; }
  .upload-btn:hover { transform: translateY(-1px); }
  .upload-btn.image { background: linear-gradient(135deg, #2a6a88, #103040); }
  .upload-btn.video { background: linear-gradient(135deg, #6a3a8a, #2a103a); }
  .upload-btn.audio { background: linear-gradient(135deg, #3a8a3a, #10401a); }
  .upload-btn.uploading { opacity:.5; pointer-events:none; }
  #uploadStatus { font-size:13px; opacity:.75; }
  .mine-box { grid-column: 1 / -1; padding: 12px 14px; border-radius: 14px;
              background: linear-gradient(135deg, #2a1b1b, #401010);
              box-shadow: 0 8px 28px rgba(0,0,0,.6); margin-top: 4px;
              display: none; }
  .mine-box.show { display: block; }
  .mine-box .title { font-weight: 800; margin-bottom: 8px; color: #ffc8c8; }
  .mine-row { display: flex; flex-wrap: wrap; gap: 8px; }
  .mine-btn { flex: 1 1 140px; padding: 10px 12px; border: 1px solid #a06060;
              border-radius: 10px; background: #6a1f1f; color: #fff;
              font-weight: 700; font-size: 15px; cursor: pointer; }
  .mine-btn:hover { background: #8a2828; }
  .mine-btn.all  { background: #8a2828; border-color: #c06060; }
  .mine-btn[disabled] { opacity:.35; cursor: not-allowed; }
  footer { text-align:center; padding:14px; opacity:.5; font-size:12px; }
  .flash { position:fixed; inset:0; background:#fff; opacity:0; pointer-events:none;
           transition: opacity .08s; z-index:9998; }
  #toast { position:fixed; top:18px; left:50%; transform:translateX(-50%);
           padding:8px 14px; border-radius:8px; background:#c02020; color:#fff;
           font-weight:700; font-size:14px; opacity:0; transition:opacity .2s;
           pointer-events:none; z-index:10000; }
  #toast.show { opacity:1; }
</style>
</head>
<body>
<header>
  <h1>POCOBoard</h1>
  <div id="who">
    <input id="nameInput" type="text" maxlength="32" placeholder="表示名 (あなたの名前)"
           autocomplete="off" spellcheck="false"
           style="padding:6px 10px; border-radius:8px; border:1px solid #555;
                  background:#0a0a0f; color:#eee; font-size:14px; width:180px;">
    <span id="myId" style="margin-left:8px; font-family:Consolas,monospace; opacity:.7; font-size:12px;"></span>
  </div>
  <div id="status">
    受付:<span id="acc" class="pill">...</span>
    音量:<span id="vol" class="pill">...</span>
  </div>
</header>

<main>
  <button class="fx bomb"   id="btnBomb">BOMB</button>
  <button class="fx clap"   id="btnClap">CHEER</button>
  <button class="fx talk"   id="btnTalk">🎙 TALK</button>
  <button class="fx hearts" id="btnHearts">HEARTS</button>
  <button class="fx stars"  id="btnStars">STARS</button>
  <button class="fx snow"   id="btnSnow">SNOW</button>

  <div class="upload-box" id="uploadBox">
    <div class="upload-row">
      <label class="upload-btn image">📷 写真を送る
        <input type="file" accept="image/*" hidden id="upImage">
      </label>
      <label class="upload-btn video">🎬 動画を送る
        <input type="file" accept="video/*" hidden id="upVideo">
      </label>
      <label class="upload-btn audio">🎵 音声ファイル
        <input type="file" accept="audio/*" hidden id="upAudio">
      </label>
    </div>
    <div id="uploadStatus"></div>
  </div>

  <!-- Per-user "cancel mine" controls. Appears only while at least one of the
       media slots is held by THIS browser (verified by cookie on the server). -->
  <div class="mine-box" id="mineBox">
    <div class="title">🧍 自分が送ったメディアの取消</div>
    <div class="mine-row">
      <button class="mine-btn" id="btnMineImage" disabled>📷 画像を消す</button>
      <button class="mine-btn" id="btnMineVideo" disabled>🎬 動画を止める</button>
      <button class="mine-btn" id="btnMineAudio" disabled>🎵 音声を止める</button>
      <button class="mine-btn all" id="btnMineAll">🛑 自分のぜんぶ取消</button>
    </div>
    <div style="font-size:12px; opacity:.75; margin-top:6px;">
      ※ 他のユーザが出したものは取消できません。
    </div>
  </div>

  <div class="marquee-box">
    <div class="marquee-row">
      <strong>📢 横スクロール</strong>
      <span id="mqCount" style="margin-left:auto">0 / 200</span>
    </div>
    <textarea id="mqText" maxlength="1000"
      placeholder="例: &lt;r&gt;おしらせ&lt;/&gt; &lt;big&gt;19時&lt;/big&gt;から開始します"></textarea>
    <div class="marquee-row">
      <button class="mkp mkp-r" data-tag="r">赤</button>
      <button class="mkp mkp-y" data-tag="y">黄</button>
      <button class="mkp mkp-g" data-tag="g">緑</button>
      <button class="mkp mkp-c" data-tag="c">水</button>
      <button class="mkp mkp-b" data-tag="b">青</button>
      <button class="mkp mkp-m" data-tag="m">紫</button>
      <button class="mkp mkp-o" data-tag="o">橙</button>
      <button class="mkp mkp-w" data-tag="w">白</button>
      <span class="sep"></span>
      <button class="mkp mkp-sz" data-tag="small">小</button>
      <button class="mkp mkp-sz" data-tag="s2">中</button>
      <button class="mkp mkp-sz" data-tag="big">大</button>
      <span class="sep"></span>
      <button class="mkp mkp-u"  data-tag="u">下線</button>
      <button class="mkp mkp-hl" data-tag="hl">強調</button>
      <button class="mkp" data-tag="/">リセット</button>
      <span class="sep"></span>
      <button class="mkp" data-tag="ue"    title="上部に3秒固定">上</button>
      <button class="mkp" data-tag="shita" title="下部に3秒固定">下</button>
      <span class="sep"></span>
      <button class="mkp-speed on" data-speed="1">x1</button>
      <button class="mkp-speed" data-speed="2">x2</button>
      <button class="mkp-speed" data-speed="3">x3</button>
      <button class="mkp-speed" data-speed="4">x4</button>
      <button class="mkp-speed" data-speed="5">x5</button>
      <span class="sep"></span>
      <button class="send" id="btnMqSend">流す</button>
      <button class="stop" id="btnMqStop">停止</button>
    </div>
  </div>
</main>

<footer><span style="opacity:.8; font-weight:600; letter-spacing:1px;">Programmed by ぽこちゃ技術枠　おわ</span></footer>

<div class="flash" id="flash"></div>
<div id="toast"></div>

<script>
const API_BASE = (() => {
  let p = location.pathname;
  if (p.endsWith('/')) return p;
  const i = p.lastIndexOf('/');
  return i >= 0 ? p.substring(0, i + 1) : '/';
})();
function api(path) { return API_BASE + path.replace(/^\/+/, ''); }

// ============ Identity: per-browser cookie + display name ============
// The server sets `poco_client` on first visit; we never touch it.
// We maintain a display-name in the `poco_name` cookie and surface it
// with every request via the X-Poco-Name header (so the server sees the
// latest name even before the cookie round-trips).
function readCookie(name) {
  const m = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'));
  return m ? decodeURIComponent(m[1]) : '';
}
function writeCookie(name, value, days) {
  const d = new Date();
  d.setTime(d.getTime() + (days || 365) * 864e5);
  document.cookie = name + '=' + encodeURIComponent(value)
    + '; expires=' + d.toUTCString() + '; path=/; SameSite=Lax';
}

let myName = readCookie('poco_name');
let myId   = '';    // populated from /status once the cookie round-trips
const nameInput = document.getElementById('nameInput');
const myIdLabel = document.getElementById('myId');
nameInput.value = myName;

function pushName() {
  myName = nameInput.value.trim().slice(0, 32);
  writeCookie('poco_name', myName, 365);
  // Tell the server immediately so it logs a NAME line before any FX fires.
  fetch(api('name'), {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ name: myName }),
    credentials: 'same-origin',
  }).catch(() => {});
  updateIdLabel();
}
nameInput.addEventListener('change', pushName);
nameInput.addEventListener('blur', pushName);

function updateIdLabel() {
  const short = (myId || '').slice(0, 8);
  myIdLabel.textContent = short ? ('#' + short) : '';
}

// Wrap fetch: attach X-Poco-Name header + credentials for cookie round-trip.
const _fetch = window.fetch;
window.fetch = function(url, opts) {
  opts = opts || {};
  opts.credentials = opts.credentials || 'same-origin';
  const hdrs = new Headers(opts.headers || {});
  if (myName) hdrs.set('X-Poco-Name', myName);
  opts.headers = hdrs;
  return _fetch(url, opts);
};

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

async function refreshStatus() {
  try {
    const r = await fetch(api('status'), { cache: 'no-store' });
    const j = await r.json();
    const acc = document.getElementById('acc');
    acc.textContent = j.accept ? 'ON' : 'OFF';
    acc.className = 'pill ' + (j.accept ? 'on' : 'off');
    document.getElementById('vol').textContent = j.volume + '/100';
    const disable = !j.accept;
    ['btnBomb','btnClap','btnHearts','btnStars','btnSnow'].forEach(id => {
      document.getElementById(id).disabled = disable;
    });
    if (!talkActive) document.getElementById('btnTalk').disabled = disable;
    if (j.me && j.me.id && !myId) {
      myId = j.me.id;
      updateIdLabel();
      // Push display name after the first status round-trip so the server's
      // log records our preferred name even if we joined mid-session.
      if (myName) pushName();
    }
    updateMineControls(j.mine || {image:false, video:false, audio:false});
  } catch (e) { /* network blip */ }
}

function updateMineControls(mine) {
  const box = document.getElementById('mineBox');
  const any = !!(mine.image || mine.video || mine.audio);
  box.classList.toggle('show', any);
  document.getElementById('btnMineImage').disabled = !mine.image;
  document.getElementById('btnMineVideo').disabled = !mine.video;
  document.getElementById('btnMineAudio').disabled = !mine.audio;
  document.getElementById('btnMineAll').disabled   = !any;
}

async function stopMine(kind) {
  try {
    const r = await fetch(api('my/stop?kind=' + encodeURIComponent(kind)),
                          { method: 'POST' });
    if (!r.ok) {
      toast('取消失敗: ' + r.status);
    } else {
      refreshStatus();
    }
  } catch(e) { toast(e.message); }
}
document.getElementById('btnMineImage').onclick = () => stopMine('image');
document.getElementById('btnMineVideo').onclick = () => stopMine('video');
document.getElementById('btnMineAudio').onclick = () => stopMine('audio');
document.getElementById('btnMineAll').onclick   = () => stopMine('all');

function flashScreen(color) {
  const f = document.getElementById('flash');
  f.style.background = color || '#fff';
  f.style.opacity = '1';
  setTimeout(() => { f.style.opacity = '0'; }, 120);
}

async function trigger(path) {
  try {
    const r = await fetch(api(path), { method: 'POST' });
    if (!r.ok) {
      let reason = r.status;
      try { const j = await r.json(); if (j.reason) reason = j.reason; } catch(e){}
      toast('拒否: ' + reason);
    }
  } catch(e) { toast(e.message); }
}

document.getElementById('btnBomb').onclick   = () => { flashScreen('#fff');    trigger('bomb'); };
document.getElementById('btnClap').onclick   = () => { flashScreen('#ffe066'); trigger('clap'); };
document.getElementById('btnHearts').onclick = () => { flashScreen('#ffaacc'); trigger('hearts'); };
document.getElementById('btnStars').onclick  = () => { flashScreen('#ffffaa'); trigger('stars'); };
document.getElementById('btnSnow').onclick   = () => { flashScreen('#ddeeff'); trigger('snow'); };

// ============ TALK: mic capture → POST /talk every ~500ms ============
const TALK_TARGET_SR = 16000;
const TALK_CHUNK_MS  = 500;
let talkActive = false;
let talkCtx = null, talkStream = null, talkProc = null, talkSrc = null;
let talkFrames = [];
let talkSendTimer = null;
let talkWatchdog = null;
let talkInflight = 0;         // open fetch() count — guards against pile-up
let talkConsecErrors = 0;     // consecutive network errors for backoff
// Diagnostics — surfaced below the TALK button so problems are visible.
let talkStats = { sent: 0, bytes: 0, errors: 0, lastErr: '' };

function ensureTalkStatusLine() {
  let el = document.getElementById('talkStatus');
  if (el) return el;
  const btn = document.getElementById('btnTalk');
  el = document.createElement('div');
  el.id = 'talkStatus';
  el.style.cssText = 'font-size:11px; opacity:.75; margin-top:4px; '
    + 'text-align:center; font-family:Consolas,monospace; grid-column: auto;';
  btn.insertAdjacentElement('afterend', el);
  return el;
}

function renderTalkStatus(extra) {
  const el = ensureTalkStatusLine();
  if (!talkActive && !extra) { el.textContent = ''; return; }
  const secure = window.isSecureContext ? 'HTTPS ✓' : 'HTTP ✗';
  const kb = (talkStats.bytes / 1024).toFixed(1);
  const msg = talkActive
    ? `${secure}  /  送信 ${talkStats.sent}件 (${kb} KB)  /  エラー ${talkStats.errors}`
    : (extra || '');
  el.textContent = msg + (talkStats.lastErr ? '  [' + talkStats.lastErr + ']' : '');
  el.style.color = talkStats.errors > 0 ? '#ff8080' : '';
}

function updateTalkUi() {
  const btn = document.getElementById('btnTalk');
  if (talkActive) {
    btn.classList.add('recording');
    btn.textContent = '🔴 REC — tap to stop';
    btn.disabled = false;
  } else {
    btn.classList.remove('recording');
    btn.textContent = '🎙 TALK';
  }
  renderTalkStatus();
}

function drainAndSend() {
  if (talkFrames.length === 0) return;
  // If several requests are already in flight the network can't keep up —
  // drop this batch rather than letting browser memory balloon.
  if (talkInflight >= 4) {
    talkFrames = [];
    talkStats.errors++;
    talkStats.lastErr = 'backpressure';
    renderTalkStatus();
    return;
  }
  let total = 0;
  for (const f of talkFrames) total += f.length;
  const merged = new Float32Array(total);
  let p = 0;
  for (const f of talkFrames) { merged.set(f, p); p += f.length; }
  talkFrames = [];

  const srcSr = talkCtx ? talkCtx.sampleRate : TALK_TARGET_SR;
  let resampled;
  if (Math.abs(srcSr - TALK_TARGET_SR) < 1) {
    resampled = merged;
  } else {
    const ratio = srcSr / TALK_TARGET_SR;
    const outLen = Math.floor(merged.length / ratio);
    resampled = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {
      const x = i * ratio;
      const i0 = Math.floor(x);
      const frac = x - i0;
      const s0 = merged[i0] || 0;
      const s1 = merged[i0 + 1] || 0;
      resampled[i] = s0 + (s1 - s0) * frac;
    }
  }
  const pcm = new Int16Array(resampled.length);
  for (let i = 0; i < resampled.length; i++) {
    let s = resampled[i];
    if (s > 1) s = 1; else if (s < -1) s = -1;
    pcm[i] = (s * 32767) | 0;
  }
  if (pcm.length === 0) return;

  const bytes = pcm.byteLength;
  talkInflight++;
  // 4s timeout so a hung connection doesn't keep piling inflight counters.
  const ac = ('AbortController' in window) ? new AbortController() : null;
  const timer = ac ? setTimeout(() => { try { ac.abort(); } catch(_){} }, 4000) : null;
  fetch(api('talk?sr=' + TALK_TARGET_SR), {
    method: 'POST',
    headers: {'Content-Type': 'application/octet-stream'},
    body: pcm.buffer,
    signal: ac ? ac.signal : undefined,
  }).then(r => {
    if (r.ok) {
      talkStats.sent++;
      talkStats.bytes += bytes;
      talkStats.lastErr = '';
      talkConsecErrors = 0;
    } else {
      talkStats.errors++;
      talkStats.lastErr = 'HTTP ' + r.status;
      talkConsecErrors++;
    }
    renderTalkStatus();
  }).catch(e => {
    talkStats.errors++;
    talkStats.lastErr = e.message || 'network';
    talkConsecErrors++;
    renderTalkStatus();
  }).finally(() => {
    if (timer) clearTimeout(timer);
    talkInflight = Math.max(0, talkInflight - 1);
  });
}

// Periodic health check while TALK is on.  Catches the common failure modes:
//  (1) AudioContext suspended (tab backgrounded on mobile browsers)
//  (2) MediaStreamTrack ended (headset unplugged, browser yanked the device)
//  (3) Sustained network errors — restart the capture to shed any bad state.
async function talkHealthCheck() {
  if (!talkActive) return;
  if (talkCtx && talkCtx.state === 'suspended') {
    try { await talkCtx.resume(); } catch(_){}
  }
  const track = talkStream && talkStream.getAudioTracks &&
                talkStream.getAudioTracks()[0];
  const dead = !track || track.readyState === 'ended' ||
               (talkCtx && talkCtx.state === 'closed');
  if (dead || talkConsecErrors >= 10) {
    talkStats.lastErr = dead ? 'mic lost — restarting' : 'too many errors — restarting';
    renderTalkStatus();
    try { await talkStop(); } catch(_){}
    // small delay so the browser has time to release the device before re-opening
    setTimeout(() => { if (document.getElementById('btnTalk').dataset.shouldBeOn === '1') {
      talkStart();
    }}, 400);
  }
}

async function talkStart() {
  talkStats = { sent: 0, bytes: 0, errors: 0, lastErr: '' };
  if (!window.isSecureContext) {
    const url = location.href;
    renderTalkStatus('マイク不可: このURL (' + url + ') は Secure Context ではありません。HTTPS で開き直してください。');
    alert('マイクは HTTPS か localhost でしか開けません。\nこのページの URL を HTTPS に変えるか、'
        + 'リバースプロキシ経由でアクセスしてください。\n\n現在の URL:\n' + url);
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    renderTalkStatus('マイク API がこのブラウザで使えません。');
    alert('このブラウザは getUserMedia に対応していません。');
    return;
  }
  try {
    talkStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, noiseSuppression: true,
               echoCancellation: true, autoGainControl: true }
    });
  } catch (e) {
    renderTalkStatus('マイク取得失敗: ' + e.message);
    alert('マイクを開けませんでした: ' + e.message +
          '\n(HTTPS または localhost でアクセスしているか確認してください)');
    return;
  }
  const Ctx = window.AudioContext || window.webkitAudioContext;
  try { talkCtx = new Ctx({sampleRate: TALK_TARGET_SR}); }
  catch (e) { talkCtx = new Ctx(); }

  talkSrc  = talkCtx.createMediaStreamSource(talkStream);
  talkProc = talkCtx.createScriptProcessor(4096, 1, 1);
  talkProc.onaudioprocess = (ev) => {
    if (!talkActive) return;
    talkFrames.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
  };
  talkSrc.connect(talkProc);
  const mute = talkCtx.createGain();
  mute.gain.value = 0;
  talkProc.connect(mute);
  mute.connect(talkCtx.destination);

  talkActive = true;
  talkConsecErrors = 0;
  talkInflight = 0;
  talkSendTimer = setInterval(drainAndSend, TALK_CHUNK_MS);
  talkWatchdog  = setInterval(talkHealthCheck, 1500);
  updateTalkUi();
}

async function talkStop() {
  talkActive = false;
  if (talkSendTimer) { clearInterval(talkSendTimer); talkSendTimer = null; }
  if (talkWatchdog)  { clearInterval(talkWatchdog);  talkWatchdog  = null; }
  drainAndSend();
  try { talkProc && talkProc.disconnect(); } catch(e){}
  try { talkSrc  && talkSrc.disconnect();  } catch(e){}
  if (talkStream) { talkStream.getTracks().forEach(t => t.stop()); }
  if (talkCtx)    { try { await talkCtx.close(); } catch(e){} }
  talkCtx = talkStream = talkProc = talkSrc = null;
  updateTalkUi();
}

document.getElementById('btnTalk').onclick = () => {
  const btn = document.getElementById('btnTalk');
  if (talkActive) {
    btn.dataset.shouldBeOn = '0';
    talkStop();
  } else {
    btn.dataset.shouldBeOn = '1';
    talkStart();
  }
};

// ============ MARQUEE composer ============
const mqTextEl  = document.getElementById('mqText');
const mqCountEl = document.getElementById('mqCount');
const MQ_PLAIN_MAX = 200;

function mqPlainLen(s) { return s.replace(/<[^>]*>/g, '').length; }
function mqUpdateCount() {
  const n = mqPlainLen(mqTextEl.value);
  mqCountEl.textContent = n + ' / ' + MQ_PLAIN_MAX;
  mqCountEl.style.color = (n > MQ_PLAIN_MAX) ? '#ff6a6a' : '';
}
mqTextEl.addEventListener('input', mqUpdateCount);
mqUpdateCount();

const MQ_COLOR_TAGS = ['r','g','b','y','c','m','w','o',
                       'red','green','blue','yellow','cyan','purple',
                       'white','orange','pink'];
const MQ_STANDALONE_TAGS = ['ue','shita','top','bottom','naka','middle'];
function mqInsert(tag) {
  const el = mqTextEl;
  const s = el.selectionStart, e = el.selectionEnd;
  const v = el.value;
  if (tag === '/') {
    const insert = '</>';
    el.value = v.slice(0, s) + insert + v.slice(e);
    const p = s + insert.length;
    el.focus(); el.setSelectionRange(p, p);
    mqUpdateCount();
    return;
  }
  if (MQ_STANDALONE_TAGS.includes(tag)) {
    // Niconico-style position tag: prefix the whole message.
    const prefix = '<' + tag + '>';
    el.value = prefix + v;
    el.focus(); el.setSelectionRange(el.value.length, el.value.length);
    mqUpdateCount();
    return;
  }
  const open = '<' + tag + '>';
  const close = MQ_COLOR_TAGS.includes(tag) ? '</>' : '</' + tag + '>';
  el.value = v.slice(0, s) + open + v.slice(s, e) + close + v.slice(e);
  const p = (s === e) ? s + open.length : e + open.length + close.length;
  el.focus(); el.setSelectionRange(p, p);
  mqUpdateCount();
}
document.querySelectorAll('.mkp').forEach(btn => {
  btn.addEventListener('click', () => mqInsert(btn.dataset.tag));
});

let mqSpeed = 1;
document.querySelectorAll('.mkp-speed').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.mkp-speed').forEach(x => x.classList.remove('on'));
    btn.classList.add('on');
    mqSpeed = parseInt(btn.dataset.speed, 10);
  });
});

document.getElementById('btnMqSend').onclick = async () => {
  const text = mqTextEl.value.trim();
  if (!text) return;
  if (mqPlainLen(text) > MQ_PLAIN_MAX) {
    alert('本文が長すぎます (最大 ' + MQ_PLAIN_MAX + ' 文字)');
    return;
  }
  try {
    const r = await fetch(api('marquee?speed=' + mqSpeed), {
      method: 'POST',
      headers: {'Content-Type': 'text/plain; charset=utf-8'},
      body: text
    });
    if (!r.ok) {
      let reason = r.status;
      try {
        const j = await r.json();
        if (j.reason === 'empty')        reason = '本文が空です。';
        else if (j.reason === 'disabled') reason = '受付OFFです。';
        else if (j.reason) reason = r.status + ': ' + j.reason;
      } catch(e) {}
      toast('送信失敗: ' + reason);
    }
  } catch(e) { toast(e.message); }
};
document.getElementById('btnMqStop').onclick = async () => {
  try { await fetch(api('marquee/stop'), { method: 'POST' }); } catch(e) {}
};

// ============ UPLOAD (photo / video / audio) ============
const upStatus = document.getElementById('uploadStatus');
function setUpStatus(msg, isErr) {
  upStatus.textContent = msg || '';
  upStatus.style.color = isErr ? '#ff8080' : '';
}

async function handleUpload(inputEl, kind) {
  const f = inputEl.files && inputEl.files[0];
  inputEl.value = '';
  if (!f) return;
  const maxMB = kind === 'image' ? 25 : kind === 'audio' ? 50 : 200;
  if (f.size > maxMB * 1024 * 1024) {
    setUpStatus(`${f.name} はサイズオーバー (最大 ${maxMB} MB)`, true);
    return;
  }
  const lbl = inputEl.parentElement;
  lbl.classList.add('uploading');
  const origText = lbl.childNodes[0].nodeValue;
  lbl.childNodes[0].nodeValue = `アップロード中… ${f.name}`;

  // XHR so we can show progress on bigger files.
  try {
    await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const q = new URLSearchParams({ type: kind, filename: f.name });
      xhr.open('POST', api('upload?' + q), true);
      xhr.withCredentials = true;
      if (myName) xhr.setRequestHeader('X-Poco-Name', myName);
      xhr.setRequestHeader('Content-Type', f.type || 'application/octet-stream');
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.floor(e.loaded / e.total * 100);
          lbl.childNodes[0].nodeValue = `アップロード中 ${pct}% — ${f.name}`;
        }
      };
      xhr.onload  = () => xhr.status >= 200 && xhr.status < 300 ? resolve() : reject(new Error(`HTTP ${xhr.status}`));
      xhr.onerror = () => reject(new Error('network error'));
      xhr.send(f);
    });
    setUpStatus(`✓ 送信しました: ${f.name}`);
  } catch (e) {
    setUpStatus(`✗ ${f.name}: ${e.message}`, true);
  } finally {
    lbl.classList.remove('uploading');
    lbl.childNodes[0].nodeValue = origText;
  }
}

document.getElementById('upImage').addEventListener('change', e => handleUpload(e.target, 'image'));
document.getElementById('upVideo').addEventListener('change', e => handleUpload(e.target, 'video'));
document.getElementById('upAudio').addEventListener('change', e => handleUpload(e.target, 'audio'));

refreshStatus();
setInterval(refreshStatus, 2000);
</script>
</body>
</html>
"""
