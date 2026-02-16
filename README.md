# カメラストリーミングサーバー

Logitech USB カメラ (Brio 100) の映像をブラウザからリアルタイム視聴できる Web サーバーです。

## セットアップ

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 起動

```bash
# デフォルト (0.0.0.0:8080, /dev/video0, 1280x720)
python app.py

# デバイス番号で指定
python app.py --device 0

# デバイスパスで指定（udev シンボリックリンク対応）
python app.py --device /dev/camera-brio

# カメラ名で自動検出
python app.py --device "Brio 100"
python app.py --camera-name "Brio 100"

# その他のオプション
python app.py --device /dev/camera-brio --width 1920 --height 1080 --fps 30 --port 8080

# 接続中のカメラ一覧を表示
python app.py --list-cameras
```

### `--device` の指定方法

| 形式 | 例 | 説明 |
|------|-----|------|
| デバイス番号 | `--device 0` | `/dev/video0` として開く |
| デバイスパス | `--device /dev/camera-brio` | パスをそのまま使用（udev シンボリックリンク推奨） |
| カメラ名 | `--device "Brio 100"` | 接続中のカメラから名前で自動検出 |
| 省略 | *(なし)* | `/dev/video0` を使用 |

## カメラデバイスの固定（udev ルール）

USB カメラはポートの挿し替えや再起動でデバイス番号（`/dev/video0`, `/dev/video1`, ...）が変わることがあります。
udev ルールを使って `/dev/camera-brio` のような固定のシンボリックリンクを作成できます。

同梱の `99-camera-server.rules` は Logitech Brio 100 用のルールです。
別のカメラを使う場合は Vendor ID / Product ID を調べて書き換えてください。

```bash
# カメラの USB 情報を調べる
udevadm info --name=/dev/video0 --attribute-walk | grep -E 'idVendor|idProduct'

# ルールの手動インストール
sudo cp 99-camera-server.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=video4linux

# リンクが作成されたか確認
ls -la /dev/camera-brio
```

> **注:** `./service.sh install` を実行すると udev ルールも自動的にインストールされます。

## ブラウザでアクセス

| 場所 | URL |
|------|-----|
| ローカル | http://localhost:8080 |
| 同一LAN | http://<このPCのIPアドレス>:8080 |

LAN内のIPアドレスは以下で確認できます：

```bash
hostname -I
```

## 自宅（外出先）から見る方法

### 方法 1: Tailscale（推奨・簡単）

1. このPCと閲覧デバイスの両方に [Tailscale](https://tailscale.com/) をインストール
2. 同じアカウントでログイン
3. `http://<Tailscale上のIP>:8080` でアクセス

```bash
# インストール
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
tailscale ip  # ← このIPでアクセス
```

### 方法 2: Cloudflare Tunnel（ドメイン不要で HTTPS 化）

```bash
# cloudflared インストール後
cloudflared tunnel --url http://localhost:8080
```

表示された URL をブラウザで開くだけ。

### 方法 3: ルーターのポートフォワーディング

ルーターの管理画面で外部ポート → `このPC:8080` に転送設定。
※ セキュリティリスクがあるため非推奨。

## 常駐化（systemd サービス）

PC起動時にカメラサーバーを自動起動させるには、systemd サービスとして登録します。
`service.sh install` は udev ルールのインストールも同時に行います。

```bash
# インストール（udev ルール＋サービス登録＋自動起動＋即時起動）
./service.sh install

# ステータス確認
./service.sh status

# アンインストール（停止＋自動起動解除＋udev ルール削除）
./service.sh uninstall
```

### 手動操作

```bash
# 停止 / 起動 / 再起動
sudo systemctl stop camera-server
sudo systemctl start camera-server
sudo systemctl restart camera-server

# ログ確認
sudo journalctl -u camera-server -f
```

### 設定変更

起動オプションを変更したい場合は `camera-server.service` の `ExecStart` 行を編集して再インストールしてください。

```ini
ExecStart=/home/katsuyuki/github/camera-server/.venv/bin/python app.py --device /dev/camera-brio --width 1920 --height 1080
```

## API

| エンドポイント | メソッド | 説明 |
|----------------|----------|------|
| `/` | GET | ビューアーページ |
| `/video_feed` | GET | MJPEG ストリーム |
| `/snapshot` | GET | 静止画 JPEG |
| `/api/status` | GET | カメラ状態 JSON |
| `/api/cameras` | GET | 接続中のカメラ一覧 JSON |
| `/api/controls` | GET | カメラ設定値の取得 |
| `/api/controls` | POST | カメラ設定値の変更（JSON: `{"brightness": 128, ...}`） |
| `/api/controls/reset` | POST | カメラ設定をデフォルトに戻す |
