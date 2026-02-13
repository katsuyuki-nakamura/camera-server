"""
カメラストリーミングサーバー
Logitech USB カメラの映像を MJPEG over HTTP でブラウザに配信する。
"""

import argparse
import os
import secrets
import subprocess
import threading
import time

import cv2
from flask import Flask, Response, render_template, jsonify, request, make_response

app = Flask(__name__)

# ─── 認証 ────────────────────────────────────────────────────────────────────

AUTH_USERNAME = ""
AUTH_PASSWORD = ""


def check_auth(username: str, password: str) -> bool:
    """ユーザー名とパスワードを検証する。"""
    return (secrets.compare_digest(username, AUTH_USERNAME)
            and secrets.compare_digest(password, AUTH_PASSWORD))


def authenticate():
    """401 レスポンスを返して Basic 認証を要求する。"""
    resp = make_response("認証が必要です", 401)
    resp.headers["WWW-Authenticate"] = 'Basic realm="Camera Server"'
    return resp


@app.before_request
def require_auth():
    """全リクエストに Basic 認証を要求する。"""
    if not AUTH_USERNAME:
        return  # 認証未設定なら素通し
    auth = request.authorization
    if not auth or not check_auth(auth.username, auth.password):
        return authenticate()

# ─── カメラ管理 ──────────────────────────────────────────────────────────────

class CameraStream:
    """スレッドセーフなカメラキャプチャ。最新フレームだけ保持する。"""

    def __init__(self, device: int = 0, width: int = 1280, height: int = 720,
                 fps: int = 30):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps

        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False

    def start(self):
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"カメラ /dev/video{self.device} を開けません")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        self.running = True
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()
        print(f"カメラ開始: /dev/video{self.device}  "
              f"{int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x"
              f"{int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))} @ "
              f"{int(self.cap.get(cv2.CAP_PROP_FPS))}fps")

    def _capture_loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
            else:
                time.sleep(0.01)

    def get_frame(self):
        with self.lock:
            return self.frame

    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


camera = CameraStream()

# ─── ストリーミング ──────────────────────────────────────────────────────────

def generate_mjpeg(quality: int = 80):
    """MJPEG フレームを yield するジェネレータ。"""
    encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
    while True:
        frame = camera.get_frame()
        if frame is None:
            time.sleep(0.05)
            continue
        ok, buf = cv2.imencode(".jpg", frame, encode_params)
        if not ok:
            continue
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + buf.tobytes() + b"\r\n"
        )


# ─── ルーティング ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/video_feed")
def video_feed():
    """MJPEG ストリームエンドポイント。"""
    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/snapshot")
def snapshot():
    """現在のフレームを JPEG で返す。"""
    frame = camera.get_frame()
    if frame is None:
        return "カメラ映像なし", 503
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return "エンコード失敗", 500
    return Response(buf.tobytes(), mimetype="image/jpeg")


@app.route("/api/status")
def status():
    return jsonify({
        "camera": camera.device,
        "resolution": f"{camera.width}x{camera.height}",
        "fps": camera.fps,
        "running": camera.running,
    })

# ─── カメラ設定 API ────────────────────────────────────────────────────────────────

# v4l2 で調整可能なコントロールとその範囲
CAMERA_CONTROLS = {
    "brightness":           {"min": 0, "max": 255, "step": 1, "default": 128, "label": "明るさ"},
    "contrast":             {"min": 0, "max": 255, "step": 1, "default": 128, "label": "コントラスト"},
    "saturation":           {"min": 0, "max": 255, "step": 1, "default": 128, "label": "彩度"},
    "sharpness":            {"min": 0, "max": 255, "step": 1, "default": 128, "label": "シャープネス"},
    "gain":                 {"min": 0, "max": 255, "step": 1, "default": 0,   "label": "ゲイン"},
    "white_balance_automatic": {"min": 0, "max": 1, "step": 1, "default": 1, "label": "オートホワイトバランス", "type": "bool"},
    "white_balance_temperature": {"min": 2800, "max": 7500, "step": 1, "default": 4000, "label": "ホワイトバランス温度"},
    "backlight_compensation": {"min": 0, "max": 1, "step": 1, "default": 1, "label": "逆光補正", "type": "bool"},
    "auto_exposure":        {"min": 1, "max": 3, "step": 2, "default": 3, "label": "自動露出",
                             "type": "menu", "options": {"1": "マニュアル", "3": "自動"}},
    "exposure_time_absolute": {"min": 5, "max": 2500, "step": 1, "default": 156, "label": "露出時間"},
    "power_line_frequency":  {"min": 0, "max": 2, "step": 1, "default": 2, "label": "電源周波数",
                             "type": "menu", "options": {"0": "無効", "1": "50Hz", "2": "60Hz"}},
}


def _v4l2_device():
    return f"/dev/video{camera.device}"


def _get_v4l2_value(ctrl: str) -> int | None:
    """v4l2-ctl で現在値を取得する。"""
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", "-d", _v4l2_device(), "--get-ctrl", ctrl],
            stderr=subprocess.STDOUT, text=True, timeout=3,
        )
        # "brightness: 128" or "auto_exposure: 3 (Aperture Priority Mode)" の形式
        val_part = out.strip().split(":")[-1].strip()
        # 括弧以前の数値部分だけ取り出す
        val_part = val_part.split("(")[0].strip()
        return int(val_part)
    except Exception:
        return None


def _set_v4l2_value(ctrl: str, value: int) -> bool:
    """v4l2-ctl で値を設定する。"""
    try:
        subprocess.check_call(
            ["v4l2-ctl", "-d", _v4l2_device(), "--set-ctrl", f"{ctrl}={value}"],
            stderr=subprocess.STDOUT, timeout=3,
        )
        return True
    except Exception:
        return False


@app.route("/api/controls")
def get_controls():
    """全コントロールの現在値を返す。"""
    result = {}
    for name, meta in CAMERA_CONTROLS.items():
        val = _get_v4l2_value(name)
        result[name] = {**meta, "value": val}
    return jsonify(result)


@app.route("/api/controls", methods=["POST"])
def set_controls():
    """コントロール値を設定する。 JSON: {"name": value, ...}"""
    data = request.get_json(force=True)
    results = {}
    for name, value in data.items():
        if name not in CAMERA_CONTROLS:
            results[name] = {"ok": False, "error": "不明なコントロール"}
            continue
        meta = CAMERA_CONTROLS[name]
        value = int(value)
        value = max(meta["min"], min(meta["max"], value))
        ok = _set_v4l2_value(name, value)
        results[name] = {"ok": ok, "value": value}
    return jsonify(results)


@app.route("/api/controls/reset", methods=["POST"])
def reset_controls():
    """全コントロールをデフォルトに戻す。"""
    results = {}
    for name, meta in CAMERA_CONTROLS.items():
        ok = _set_v4l2_value(name, meta["default"])
        results[name] = {"ok": ok, "value": meta["default"]}
    return jsonify(results)

# ─── エントリポイント ────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="カメラストリーミングサーバー")
    parser.add_argument("--device", type=int, default=0,
                        help="カメラデバイス番号 (default: 0)")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--host", default="0.0.0.0",
                        help="バインドアドレス (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8080,
                        help="ポート番号 (default: 8080)")
    parser.add_argument("--username", default=os.environ.get("CAMERA_USER", "katsuyuki"),
                        help="認証ユーザー名 (default: katsuyuki, env: CAMERA_USER)")
    parser.add_argument("--password", default=os.environ.get("CAMERA_PASS", "wnct3594"),
                        help="認証パスワード (default: wnct3594, env: CAMERA_PASS)")
    args = parser.parse_args()

    # 認証設定
    global AUTH_USERNAME, AUTH_PASSWORD
    AUTH_USERNAME = args.username
    AUTH_PASSWORD = args.password or secrets.token_urlsafe(12)
    print(f"\n{'='*50}")
    print(f"  認証情報")
    print(f"  ユーザー名: {AUTH_USERNAME}")
    print(f"  パスワード: {AUTH_PASSWORD}")
    print(f"{'='*50}\n")

    camera.device = args.device
    camera.width = args.width
    camera.height = args.height
    camera.fps = args.fps
    camera.start()

    try:
        app.run(host=args.host, port=args.port, threaded=True)
    finally:
        camera.stop()


if __name__ == "__main__":
    main()
