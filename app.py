"""
カメラストリーミングサーバー
Logitech USB カメラの映像を MJPEG over HTTP でブラウザに配信する。
"""

import argparse
import threading
import time

import cv2
from flask import Flask, Response, render_template, jsonify

app = Flask(__name__)

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
    args = parser.parse_args()

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
