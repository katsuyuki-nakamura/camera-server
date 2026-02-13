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

# オプション指定
python app.py --device 0 --width 1920 --height 1080 --fps 30 --port 8080
```

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

```bash
# インストール（サービス登録＋自動起動＋即時起動）
./service.sh install

# ステータス確認
./service.sh status

# アンインストール（停止＋自動起動解除）
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
ExecStart=/home/katsuyuki/github/camera-server/.venv/bin/python app.py --device 0 --width 1920 --height 1080
```

## API

| エンドポイント | 説明 |
|----------------|------|
| `GET /` | ビューアーページ |
| `GET /video_feed` | MJPEG ストリーム |
| `GET /snapshot` | 静止画 JPEG |
| `GET /api/status` | カメラ状態 JSON |
