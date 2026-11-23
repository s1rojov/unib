"""Jonli ko'rish: worker ichidagi kichik HTTP server, kadrlarni faqat xotiradan beradi.

Kadrlar bazaga ham, diskka ham yozilmaydi (TZ 5-bo'lim). Server faqat ichki tarmoqda
(lokalda 127.0.0.1) tinglaydi va maxfiy token talab qiladi; brauzer unga to'g'ridan-to'g'ri
emas, Django orqali (administrator ruxsati tekshirilib) murojaat qiladi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2
import numpy as np
from django.conf import settings
from django.db import connections

from .hub import CameraHub, FaceMark

log = logging.getLogger("vision.preview")

PREVIEW_TTL_SECONDS = 15.0  # oxirgi so'rovdan keyin kamera shuncha vaqt ochiq turadi
SESSION_MARKS_FRESH_SECONDS = 2.0
MAX_PREVIEW_WIDTH = 960

# BGR ranglar
COLORS = {
    "recognized": (60, 170, 40),
    "reliable": (90, 200, 90),
    "uncertain": (0, 180, 255),
    "unknown": (60, 60, 220),
    "low_quality": (150, 150, 150),
    "small": (150, 150, 150),
    "ok": (90, 200, 90),
}


def preview_token() -> str:
    return hmac.new(settings.SECRET_KEY.encode(), b"camera-preview", hashlib.sha256).hexdigest()


def ascii_label(text: str) -> str:
    """OpenCV faqat ASCII chizadi: oʻ/gʻ va boshqa belgilarni moslaydi."""
    text = text.replace("ʻ", "'").replace("ʼ", "'").replace("‘", "'").replace("’", "'")
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def draw_marks(frame: np.ndarray, marks: list[FaceMark]) -> np.ndarray:
    h, w = frame.shape[:2]
    scale = min(1.0, MAX_PREVIEW_WIDTH / float(w))
    img = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA) if scale < 1 else frame.copy()
    for m in marks:
        x, y, bw, bh = (int(v * scale) for v in m.box)
        color = COLORS.get(m.kind, (200, 200, 200))
        cv2.rectangle(img, (x, y), (x + bw, y + bh), color, 2)
        label = ascii_label(m.label)
        (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        ty = y - 6 if y - th - 10 > 0 else y + bh + th + 6
        cv2.rectangle(img, (x, ty - th - 4), (x + tw + 6, ty + base), color, -1)
        cv2.putText(img, label, (x + 3, ty - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    return img


_cfg_cache: tuple[float, object] | None = None


def _settings():
    global _cfg_cache
    from core.models import RecognitionSettings

    if _cfg_cache is None or time.monotonic() - _cfg_cache[0] > 5:
        _cfg_cache = (time.monotonic(), RecognitionSettings.get())
    return _cfg_cache[1]


def detect_marks(entry, frame: np.ndarray, cfg) -> list[FaceMark]:
    """Sessiya bo'lmaganda: faqat yuzlarni topish va sifatni baholash (tanishsiz)."""
    from .engine import FaceEngine

    with entry.engine_lock:
        if entry.engine is None:
            entry.engine = FaceEngine(det_score_threshold=cfg.det_score_threshold)
        engine = entry.engine
        faces = engine.detect(frame, cfg.detect_max_width)
        marks = []
        for row in faces:
            q = engine.analyze(frame, row, with_feature=False).quality
            ok = q.passes(cfg.min_face_px, cfg.min_blur_var, cfg.max_yaw_deg)
            if ok:
                label = f"{q.size_px:.0f}px OK"
            else:
                parts = []
                if q.size_px < cfg.min_face_px:
                    parts.append("kichik")
                if q.blur_var < cfg.min_blur_var:
                    parts.append("xira")
                if q.yaw_deg > cfg.max_yaw_deg:
                    parts.append("burilgan")
                label = f"{q.size_px:.0f}px " + ",".join(parts)
            box = tuple(int(v) for v in row[:4])
            marks.append(FaceMark(box, "ok" if ok else "low_quality", label, int(q.size_px), ok))
    return marks


def render_snapshot(hub: CameraHub, camera_id: int):
    """(status, body, headers) qaytaradi."""
    from core.models import Camera

    cam = Camera.objects.filter(pk=camera_id).first()
    if cam is None or not cam.rtsp_url_encrypted:
        return 404, _json({"error": "Kamera topilmadi"}), {}
    entry = hub.acquire(camera_id, cam.rtsp_url, "preview", ttl=PREVIEW_TTL_SECONDS)
    frame, frame_time, seq = entry.grabber.latest()
    if frame is None:
        state = "failed" if entry.grabber.attempts else "connecting"
        return 503, _json({"state": state, "attempts": entry.grabber.attempts}), {}
    cached = entry.preview_cache
    if cached is not None and cached[0] == seq:
        return 200, cached[1], cached[2]

    fresh = entry.session_id is not None and (time.monotonic() - entry.marks_at) < SESSION_MARKS_FRESH_SECONDS
    cfg = _settings()
    marks = list(entry.marks) if fresh else detect_marks(entry, frame, cfg)
    img = draw_marks(frame, marks)
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    del img
    if not ok:
        return 500, _json({"error": "encode"}), {}
    sizes = sorted(m.size for m in marks)
    h, w = frame.shape[:2]
    headers = {
        "X-Faces": str(len(marks)),
        "X-Faces-Ok": str(sum(1 for m in marks if m.quality_ok)),
        "X-Recognized": str(sum(1 for m in marks if m.kind in ("recognized", "reliable"))),
        "X-Min-Size": str(sizes[0]) if sizes else "",
        "X-Median-Size": str(int(np.median(sizes))) if sizes else "",
        "X-Width": str(w),
        "X-Height": str(h),
        "X-Min-Face-Px": str(cfg.min_face_px),
        "X-Source": "session" if fresh else "preview",
        "X-Session": str(entry.session_id or ""),
        "X-Frame-Time": frame_time.isoformat() if frame_time else "",
    }
    body = jpg.tobytes()
    entry.preview_cache = (seq, body, headers)
    return 200, body, headers


def _json(d):
    return json.dumps(d).encode()


class _Handler(BaseHTTPRequestHandler):
    server_version = "preview"

    def log_message(self, fmt, *args):  # URL va IP lar loglanmaydi
        pass

    def _send(self, status, body, headers, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in headers.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        token = self.headers.get("X-Preview-Token", "")
        if not hmac.compare_digest(token, self.server.token):
            return self._send(403, b"{}", {}, "application/json")
        m = re.fullmatch(r"/snapshot/(\d+)\.jpg", self.path.split("?", 1)[0])
        if not m:
            return self._send(404, b"{}", {}, "application/json")
        try:
            status, body, headers = render_snapshot(self.server.hub, int(m.group(1)))
        except Exception:
            log.exception("preview failed for camera %s", m.group(1))
            status, body, headers = 500, b'{"error": "internal"}', {}
        finally:
            connections.close_all()
        self._send(status, body, headers, "image/jpeg" if status == 200 else "application/json")


class PreviewServer:
    def __init__(self, hub: CameraHub, bind: str, port: int):
        self.httpd = ThreadingHTTPServer((bind, port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.hub = hub
        self.httpd.token = preview_token()
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="preview", daemon=True)

    def start(self):
        self.thread.start()
        log.info("preview server listening on %s:%s", *self.httpd.server_address[:2])

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
