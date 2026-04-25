# POCOBoard

<img src="icon.png" width="128" align="right" alt="POCOBoard icon">

POCOBoard は、LAN 内のスマホや PC のブラウザから、配信中 PC の表示と音を即座に操作するための Windows 向けデスクトップアプリです。  
[M5Tab-Poco](https://github.com/OwaHigashi/M5Tab-Poco) の Windows 移植として、PySide6 / Qt 6 で実装しています。

配信 PC 上では次の 2 つのウィンドウが動作します。

- `Control`:
  オペレーター用。キュー確認、再生、停止、ユーザー管理、ログ確認を行います。
- `Display`:
  視聴者に見せる側。FX、画像、動画、スクロールコメントを表示します。

ブラウザ側からは、FX、TALK、スクロール、画像・動画・音声アップロードを行えます。アップロードされたメディアは即再生ではなくキューに入り、オペレーターが流すか、自動再生に任せるかを選べます。

---

## 主な機能

- 2 画面構成
  `Control` と `Display` を別モニタに配置できます。
- ブラウザ操作
  同一 LAN のスマホや PC から操作できます。
- GPU ベースの FX
  `BOMB / CHEER / HEARTS / STARS / SNOW / PETALS / AURORA / LASER / SUNSET / LEAVES`
  既存 FX も粒子量・グロー・背景演出を強化。季節 FX も追加
- TALK 音声ミックス
  複数ブラウザの音声を同時にミックスして PC スピーカへ出します。
- メディアキュー
  画像・動画・音声はキューに入り、`再生 / 次へ / 全削除 / 停止 / 自動再生ON-OFF` で運用できます。
- ユーザー単位の許可・拒否
  クライアントごとに `許可中 / 拒否中` を切り替えられます。
- スクロールコメント
  色、サイズ、固定位置タグに対応しています。
- ローカル操作
  オペレーターがローカルファイルを直接再生できます。
- リクエストログ
  誰が何を送ったかを色付きで確認できます。

---

## スクリーンショット

| キュー / 再生制御 | ユーザー管理 |
|---|---|
| <img src="docs/img/control_queue.png" width="400"> | <img src="docs/img/control_users.png" width="400"> |

| スクロール編集 | リクエストログ |
|---|---|
| <img src="docs/img/control_marquee.png" width="400"> | <img src="docs/img/control_log.png" width="400"> |

---

## 必要環境

- Windows 10 / 11 64-bit
- 配信 PC 1 台
- LAN 接続されたスマホまたは PC
- 対応ブラウザ
  Edge / Chrome / Firefox / Safari 16+

`exe` を使う場合、Python は不要です。

---

## インストール

### 1. `exe` を使う

1. リリース ZIP を展開します。
2. `POCOBoard.exe` を起動します。
3. 初回は `config.example.ini` を `config.ini` にコピーして必要な値を調整します。

例:

```text
POCOBoard/
  POCOBoard.exe
  config.ini
  config.example.ini
  _internal/
```

### 2. ソースから実行する

```bat
git clone git@github.com:OwaHigashi/POCOBoard.git
cd POCOBoard
install-deps.bat
run.bat
```

Python 3.10 以上を想定しています。

---

## 起動

起動すると `Control` と `Display` の 2 ウィンドウが開きます。

- `Control`:
  オペレーターの手元で使います。
- `Display`:
  見せたいモニタへ移動して全画面化します。

`Control` 上部に表示される URL をブラウザで開くと、リモート UI を利用できます。

例:

```text
http://192.168.1.23:8080/
```

---

## Control ウィンドウ

### 上部エリア

- `ACCEPT`
  右上のトグル。OFF にするとグローバル REJECT になります。
- `システム終了`
  右上の終了ボタン。POCOBoard を停止します。
- ステータス
  リモート URL、流れ中メッセージ数、接続中クライアント数を表示します。
- FX ボタン
  `BOMB / CHEER / HEARTS / STARS / SNOW / PETALS / AURORA / LASER / SUNSET / LEAVES / MARQUEE STOP`
- 音量スライダ
  TALK、効果音、ローカル音声ファイル再生に適用されます。

### キュータブ

キューは POCOBoard の運用の中心です。

- `停止`
  背景画像、背景動画、音声ファイル再生を止めます。
- `次へ`
  先頭のキュー項目を再生します。
- `自動再生 ON / OFF`
  アップロード到着時に即再生するか、キュー待ちにするかを切り替えます。
- `全削除`
  未再生のキュー項目だけを削除します。
- `再生中`
  現在流れている visual / audio を表示します。
- `待機中のメディア`
  各行に `再生 / 削除` があります。

補足:

- 画像と動画は同じ visual スロットを共有します。
- 音声ファイルは別スロットで流れます。
- 再生中またはキュー待ちのファイルは、自動 prune から保護されます。

### 横スクロールタブ

- コメント入力
- 色タグ、サイズタグ、固定位置タグの挿入
- 速度 `x1..x5`
- `流す / 停止`

### 表示タブ

- `Display` を出すモニタの選択
- 全画面切替
- ローカル画像 / 動画 / 音声ファイルの再生
- 画像表示秒数の調整

### ユーザータブ

- クライアント一覧
- 個別の `許可 / 拒否`
- `全員を許可 / 全員を拒否`
- 手動更新

### ログタブ

- `JOIN / NAME / TALK / UPLOAD / ADMIN` などを色付き表示
- ログ消去

---

## ブラウザ UI

ブラウザから使える主な機能は次の通りです。

- 表示名設定
- `BOMB / CHEER / HEARTS / STARS / SNOW / PETALS / AURORA / LASER / SUNSET / LEAVES`
- `TALK`
- 画像 / 動画 / 音声アップロード
- 横スクロール送信
- 自分が出したメディアの取消
  - 種類別: `画像を消す` / `動画を止める` / `音声を止める`
  - 一括: `自分のぜんぶ取消` （再生中・キュー待ち両方を一掃）

### TALK について

ブラウザのマイク利用には Secure Context が必要です。通常の LAN 上の `http://<IP>:<port>/` では、ブラウザによっては TALK が使えません。必要に応じて `localhost` や HTTPS で確認してください。

サーバ負荷が高い場合、TALK は `429 busy` を返して過負荷を明示的に落とします。無制限にキューを積み続けない実装です。

---

## スクロールタグ

### 位置

| タグ | 意味 |
|---|---|
| `<ue>` / `<top>` | 上部固定 |
| `<shita>` / `<bottom>` | 下部固定 |
| `<naka>` / `<middle>` | 横スクロール |

### 色

- 短縮タグ:
  `<r> <g> <b> <y> <c> <m> <w> <o>`
- 長いタグ:
  `<red> <green> <blue> <yellow> <cyan> <purple> <white> <orange> <pink>`

### サイズ / 装飾

- `<small>` / `<s1>`
- `<normal>` / `<s2>`
- `<big>` / `<s3>`
- `<u>...</u>`
- `<hl>...</hl>` / `<mark>...</mark>`

例:

```text
<ue><big><y>19時から開始</y></big>
<r>お知らせ</r> <u>音量に注意</u>
<shita><pink>ありがとうございました</pink>
```

---

## FX ラインアップ

- `BOMB`
  爆発フラッシュ、衝撃波、火球、煙。
- `CHEER`
  紙吹雪、スター・バースト、祝祭感のある背景。
- `HEARTS`
  ハートの上昇、柔らかいグロー、ピンク系の演出。
- `STARS`
  星のシャワー、軌跡、きらめき。
- `SNOW`
  雪片の降下、冷色グロー、冬系の背景。
- `PETALS`
  花びらの舞い。柔らかい春色の演出。
- `AURORA`
  オーロラ帯と粒子のきらめき。幻想系の演出。
- `LASER`
  ステージ・レーザーと光点。ライブ系の演出。
- `SUNSET`
  海と空に夕日が落ち、雲・帆船のシルエット・かもめが舞う夕景の演出。
- `LEAVES`
  紅葉のもみじが木立と光芒の中を舞い落ちる秋色の演出。

## HTTP API

ベース URL:

```text
http://<IP>:<port>/
```

クライアント識別には `poco_client` Cookie を使います。表示名は `poco_name` Cookie または `X-Poco-Name` ヘッダで扱います。

### エンドポイント

| Method | Path | Body / Query | 説明 |
|---|---|---|---|
| GET | `/` | - | ブラウザ UI |
| GET | `/status` | - | `{accept, volume, clients, marquee, me, mine}` |
| POST | `/bomb` | - | BOMB |
| POST | `/clap` | - | CHEER |
| POST | `/hearts` | - | HEARTS |
| POST | `/stars` | - | STARS |
| POST | `/snow` | - | SNOW |
| POST | `/petals` | - | PETALS |
| POST | `/aurora` | - | AURORA |
| POST | `/laser` | - | LASER |
| POST | `/sunset` | - | SUNSET |
| POST | `/leaves` | - | LEAVES |
| POST | `/talk?sr=16000` | Int16 LE mono PCM | TALK 音声送信 |
| POST | `/marquee?speed=1..5` | UTF-8 text | 横スクロール送信 |
| POST | `/marquee/stop` | - | 横スクロール停止 |
| POST | `/name` | `{"name":"Alice"}` | 表示名保存 |
| POST | `/upload?type=image|video|audio&filename=...` | raw binary | メディアアップロード |
| POST | `/my/stop?kind=image|video|audio|all` | - | 自分のメディアだけ止める |

### 主なエラー

| Code | reason | 説明 |
|---|---|---|
| 503 | `disabled` | グローバル REJECT |
| 403 | `blocked` | クライアントが拒否中 |
| 429 | `busy` | FX debounce または TALK サーバキュー満杯 |
| 400 | `empty` / `not_utf8` / `bad_type` / `bad_kind` | 不正リクエスト |
| 413 | `too_large_or_empty` | アップロードサイズ超過または空 |

例:

```bash
curl -X POST http://192.168.1.23:8080/bomb

curl -X POST \
  -H "Content-Type: text/plain; charset=utf-8" \
  --data-raw "<r>お知らせ</r> <big>19時から開始</big>" \
  "http://192.168.1.23:8080/marquee?speed=2"
```

---

## `config.ini`

`config.example.ini` をコピーして `config.ini` を作成します。

```ini
# ---- Network ----
http_host       = 0.0.0.0
http_port       = 8080

# ---- Audio / behaviour ----
startup_volume  = 80
accept_on_boot  = true
debounce_ms     = 300

# ---- Display window ----
display_screen  = -1
display_fullscreen_on_boot = true
display_width   = 1600
display_height  = 900

# ---- Control window ----
control_screen  = -1

# ---- Media playback ----
image_display_sec  = 180
media_min_play_sec = 60

# ---- Marquee ----
marquee_size    = 64
```

起動時オプション:

```bat
POCOBoard.exe --port 9000 --no-fullscreen --display-screen 1
```

---

## ビルド

```bat
build.bat
```

成果物は `dist\POCOBoard\` に出力されます。

---

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| ポート 8080 が使えない | `config.ini` の `http_port` を変更 |
| ブラウザから開けない | Windows Defender Firewall と LAN 接続を確認 |
| TALK が使えない | `localhost` または HTTPS で確認 |
| 動画が再生できない | 対応 codec を確認。H.264 MP4 を推奨 |
| 音が出ない | Windows の再生デバイスとアプリ音量を確認 |
| Display が別モニタに出ない | 表示タブまたは `display_screen` を確認 |
| 長時間運用でキャッシュが増える | `cache/uploads` は自動 prune されるが、再生中・キュー中ファイルは保護される |
| リバースプロキシ越しに大きい動画がアップロードできない | プロキシのリクエストバッファリングを無効化（例: Nginx の `proxy_request_buffering off;`）するか、`client_max_body_size` を引き上げる |

---

## キーボードショートカット

Display ウィンドウ上で有効:

- `F11`
  全画面切替
- `Esc`
  全画面解除
- `C`
  カーソル表示 / 非表示

---

## クレジット

- Original:
  [M5Tab-Poco](https://github.com/OwaHigashi/M5Tab-Poco)
