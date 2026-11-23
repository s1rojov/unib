"""OpenCV YuNet (yuz topish) va SFace (yuzni tanish) o'rami.

Har bir oqim (thread) o'z FaceEngine nusxasidan foydalanadi.
Kadr va yuz kesimlari faqat xotirada; hech narsa diskka yozilmaydi.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

import cv2
import numpy as np
from django.conf import settings

from .matcher import FaceQuality, estimate_yaw_deg


@dataclass
class DetectedFace:
    row: np.ndarray  # YuNet natijasi: x, y, w, h, 5 juft nuqta, ishonch
    quality: FaceQuality
    feature: np.ndarray | None = None

    @property
    def box(self):
        x, y, w, h = self.row[:4]
        return int(x), int(y), int(w), int(h)


class FaceEngine:
    def __init__(self, det_score_threshold: float = 0.8, nms_threshold: float = 0.3, top_k: int = 5000):
        self.detector = cv2.FaceDetectorYN.create(
            str(settings.YUNET_MODEL), "", (320, 320), det_score_threshold, nms_threshold, top_k
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(settings.SFACE_MODEL), "")
        self._input_size = None

    def set_score_threshold(self, value: float):
        self.detector.setScoreThreshold(float(value))

    def detect(self, image: np.ndarray, max_width: int | None = None) -> np.ndarray:
        """Yuzlarni topadi. Katta kadr aniqlash uchun kichraytiriladi, koordinatalar asl
        o'lchamga qaytariladi (tekislash asl kadrdan qilinadi)."""
        h, w = image.shape[:2]
        scale = 1.0
        src = image
        if max_width and w > max_width:
            scale = max_width / float(w)
            src = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        sh, sw = src.shape[:2]
        if self._input_size != (sw, sh):
            self.detector.setInputSize((sw, sh))
            self._input_size = (sw, sh)
        _, faces = self.detector.detect(src)
        if faces is None:
            return np.zeros((0, 15), np.float32)
        faces = faces.astype(np.float32)
        if scale != 1.0:
            faces[:, :14] /= scale
        return faces

    def align(self, image: np.ndarray, face_row: np.ndarray) -> np.ndarray:
        return self.recognizer.alignCrop(image, face_row)

    def feature(self, aligned: np.ndarray) -> np.ndarray:
        f = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
        n = float(np.linalg.norm(f))
        return f / n if n > 1e-12 else f

    @staticmethod
    def blur_variance(aligned: np.ndarray) -> float:
        gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY) if aligned.ndim == 3 else aligned
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def analyze(self, image: np.ndarray, face_row: np.ndarray, with_feature: bool = True) -> DetectedFace:
        aligned = self.align(image, face_row)
        q = FaceQuality(
            size_px=float(min(face_row[2], face_row[3])),
            blur_var=self.blur_variance(aligned),
            yaw_deg=estimate_yaw_deg(face_row[4:14]),
            det_score=float(face_row[14]),
        )
        feat = self.feature(aligned) if with_feature else None
        del aligned
        return DetectedFace(row=face_row, quality=q, feature=feat)


def decode_image(data: bytes) -> np.ndarray | None:
    """Yuklangan rasmni xotirada dekodlaydi (EXIF burilishi hisobga olinadi)."""
    buf = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return None
    # Juda katta rasmlarni kichraytirish (tezlik uchun)
    h, w = img.shape[:2]
    m = max(h, w)
    if m > 2000:
        s = 2000.0 / m
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def face_thumbnail(image: np.ndarray, box, size: int = 160, margin: float = 0.35) -> bytes:
    """Andoza yonida ko'rsatish uchun yuzning kichik kvadrat kesimi (JPEG baytlari, xotirada).

    Faqat ro'yxatga olishda (andoza yaratilganda) ishlatiladi; jonli kadrlardan kesim olinmaydi.
    """
    x, y, w, h = box
    side = int(max(w, h) * (1 + 2 * margin))
    cx, cy = x + w // 2, y + h // 2
    ih, iw = image.shape[:2]
    x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
    x1, y1 = min(iw, x0 + side), min(ih, y0 + side)
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        crop = image
    crop = cv2.resize(crop, (size, size), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else b""


_shared_engine: FaceEngine | None = None
_shared_lock = threading.Lock()


def with_shared_engine(fn):
    """Veb-jarayon uchun bitta umumiy dvigatel (andoza yaratish). Lock bilan ishlatiladi."""
    global _shared_engine
    with _shared_lock:
        if _shared_engine is None:
            _shared_engine = FaceEngine(det_score_threshold=0.8)
        return fn(_shared_engine)
