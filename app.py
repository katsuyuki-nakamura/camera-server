"""
カメラストリーミングサーバー
Logitech USB カメラの映像を MJPEG over HTTP でブラウザに配信する。
"""

import argparse
import glob
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

# ─── カメラ検出 ──────────────────────────────────────────────────────────────

def find_camera_by_name(name: str) -> str | None:
    """v4l2 デバイスの中からカメラ名で検索し、デバイスパスを返す。

    /sys/class/video4linux/videoN/name を参照して一致するデバイスを探す。
    キャプチャデバイス (index 0) のみ対象とする。
    """
    for dev_dir in sorted(glob.glob("/sys/class/video4linux/video*")):
        try:
            dev_name = open(os.path.join(dev_dir, "name")).read().strip()
            dev_index = open(os.path.join(dev_dir, "index")).read().strip()
        except OSError:
            continue
        if dev_index != "0":
            continue  # メタデータ用デバイスはスキップ
        if name.lower() in dev_name.lower():
            video_node = os.path.join("/dev", os.path.basename(dev_dir))
            print(f"カメラ検出: '{dev_name}' → {video_node}")
            return video_node
    return None


def list_cameras() -> list[dict]:
    """利用可能なカメラの一覧を返す。"""
    cameras = []
    for dev_dir in sorted(glob.glob("/sys/class/video4linux/video*")):
        try:
            dev_name = open(os.path.join(dev_dir, "name")).read().strip()
            dev_index = open(os.path.join(dev_dir, "index")).read().strip()
        except OSError:
            continue
        if dev_index != "0":
            continue
        video_node = os.path.join("/dev", os.path.basename(dev_dir))
        cameras.append({"device": video_node, "name": dev_name})
    return cameras


def resolve_device(device: str | None, camera_name: str | None) -> str:
    """--device / --camera-name 引数からデバイスパスを解決する。

    優先順位:
      1. --device にパスが指定されている場合はそのまま使う
      2. --device に数字が指定されている場合は /dev/videoN に変換
      3. --camera-name が指定されている場合は名前で検索
      4. どれも指定されていなければ /dev/video0
    """
    if device is not None:
        # パス形式 (/dev/...) ならそのまま
        if device.startswith("/"):
            return device
        # 数字ならデバイス番号として扱う
        try:
            return f"/dev/video{int(device)}"
        except ValueError:
            pass
        # 数字でもパスでもない場合はカメラ名として検索を試みる
        found = find_camera_by_name(device)
        if found:
            return found
        raise RuntimeError(f"デバイス '{device}' を解決できません")

    if camera_name:
        found = find_camera_by_name(camera_name)
        if found:
            return found
        raise RuntimeError(
            f"カメラ名 '{camera_name}' に一致するデバイスが見つかりません。"
            f"利用可能なカメラ: {list_cameras()}"
        )

    return "/dev/video0"


# ─── カメラ管理 ──────────────────────────────────────────────────────────────

class CameraStream:
    """スレッドセーフなカメラキャプチャ。最新フレームだけ保持する。"""

    def __init__(self, device: str = "/dev/video0", width: int = 1280,
                 height: int = 720, fps: int = 30):
        self.device = device      # デバイスパス (例: /dev/video0, /dev/camera-brio)
        self.width = width
        self.height = height
        self.fps = fps

        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False

    @property
    def device_display(self) -> str:
        """表示用のデバイス情報。シンボリックリンクの場合は実体も表示する。"""
        if os.path.islink(self.device):
            real = os.path.realpath(self.device)
            return f"{self.device} → {real}"
        return self.device

    def start(self):
        if not os.path.exists(self.device):
            raise RuntimeError(f"デバイス {self.device} が存在しません")
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"カメラ {self.device} を開けません")

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        self.running = True
        t = threading.Thread(target=self._capture_loop, daemon=True)
        t.start()
        print(f"カメラ開始: {self.device_display}  "
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


@app.route("/api/cameras")
def get_cameras():
    """利用可能なカメラの一覧を返す。"""
    return jsonify(list_cameras())

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
        "camera_real": os.path.realpath(camera.device) if os.path.islink(camera.device) else camera.device,
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
    """v4l2-ctl に渡すデバイスパスを返す。シンボリックリンクなら実体を解決する。"""
    dev = camera.device
    if os.path.islink(dev):
        dev = os.path.realpath(dev)
    return dev


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
    parser.add_argument("--device", type=str, default=None,
                        help="カメラデバイス (番号, パス, またはカメラ名)  "
                             "例: 0, /dev/video0, /dev/camera-brio, 'Brio 100'")
    parser.add_argument("--camera-name", default=None,
                        help="カメラ名で自動検出 (例: 'Brio 100')")
    parser.add_argument("--list-cameras", action="store_true",
                        help="利用可能なカメラを一覧表示して終了")
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

    # カメラ一覧表示モード
    if args.list_cameras:
        cameras = list_cameras()
        if not cameras:
            print("カメラが見つかりません")
        else:
            print(f"{'デバイス':<20} {'名前'}")
            print("-" * 50)
            for c in cameras:
                print(f"{c['device']:<20} {c['name']}")
        return

    # 認証設定
    global AUTH_USERNAME, AUTH_PASSWORD
    AUTH_USERNAME = args.username
    AUTH_PASSWORD = args.password or secrets.token_urlsafe(12)
    print(f"\n{'='*50}")
    print(f"  認証情報")
    print(f"  ユーザー名: {AUTH_USERNAME}")
    print(f"  パスワード: {AUTH_PASSWORD}")
    print(f"{'='*50}\n")

    # デバイス解決
    device_path = resolve_device(args.device, args.camera_name)
    camera.device = device_path
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
