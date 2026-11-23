"""Kameradan kadr olish: RTSP (OpenCV FFmpeg backend) yoki kompyuter kamerasi (indeks: 0, 1, ...).

- Faqat eng so'nggi kadr saqlanadi, eskilari tashlanadi.
- Uzilishda 2, 4, 8 … max s oraliqda cheksiz qayta urinish (to'xtatilguncha).
- URL (rekvizitlar bilan) hech qachon logga yozilmaydi.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np
from django.utils import timezone

log = logging.getLogger(__name__)


def backoff_delays(max_seconds: float = 30.0):
    d = 2.0
    while True:
        yield min(d, max_seconds)
        d = min(d * 2, max_seconds)


def _is_network(url: str) -> bool:
    return url.lower().startswith(("rtsp://", "rtsps://", "rtmp://", "http://", "https://", "udp://", "tcp://"))


def is_local_camera(url: str) -> bool:
    """Kompyuterga ulangan kamera: manzil o'rniga indeks (0, 1, ...)."""
    return url.strip().isdigit()


def open_local_camera(index: int, width: int = 1280, height: int = 720) -> cv2.VideoCapture:
    """Lokal kamerani ochadi. Windows'da DirectShow tezroq va ishonchliroq ochiladi."""
    api = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY
    cap = cv2.VideoCapture(index, api)
    if not cap.isOpened() and api != cv2.CAP_ANY:
        cap.release()
        cap = cv2.VideoCapture(index)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def open_source(url: str, open_timeout_ms: int = 10000, read_timeout_ms: int = 5000) -> cv2.VideoCapture:
    if is_local_camera(url):
        return open_local_camera(int(url))
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, open_timeout_ms, cv2.CAP_PROP_READ_TIMEOUT_MSEC, read_timeout_ms]
    return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)



class FrameGrabber(threading.Thread):
    """Kameradan uzluksiz o'qiydi va faqat eng so'nggi kadrni xotirada saqlaydi.

    Bir nechta iste'molchi (sessiya tahlili, jonli ko'rish, tekshiruv) bitta grabber'dan
    foydalanadi. Holat o'zgarishlari ro'yxatdan o'tgan tinglovchilarga yuboriladi:
    listener.on_connect(), listener.on_disconnect(attempt), listener.on_connect_failed(attempt).
    """

    def __init__(self, url: str, label: str, reconnect_max_seconds: float = 30.0,
                 open_timeout_ms: int = 10000, read_timeout_ms: int = 5000):
        super().__init__(name=f"grab-{label}", daemon=True)
        self._url = url
        self.label = label
        self.reconnect_max = reconnect_max_seconds
        self.open_timeout_ms = open_timeout_ms
        self.read_timeout_ms = read_timeout_ms
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._listeners: list = []
        self._frame: np.ndarray | None = None
        self._frame_time: datetime | None = None
        self._seq = 0
        self.connected = False
        self.attempts = 0
        self.last_error_at: float | None = None

    @property
    def url(self):
        return self._url

    def stop(self):
        self._halt.set()

    @property
    def stopped(self):
        return self._halt.is_set()

    def add_listener(self, listener):
        with self._lock:
            if listener in self._listeners:
                return
            self._listeners.append(listener)
            connected = self.connected
        if connected and hasattr(listener, "on_connect"):
            listener.on_connect()

    def remove_listener(self, listener):
        with self._lock:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _emit(self, name, *args):
        with self._lock:
            listeners = list(self._listeners)
        for li in listeners:
            fn = getattr(li, name, None)
            if fn is None:
                continue
            try:
                fn(*args)
            except Exception:
                log.exception("camera %s: listener %s failed", self.label, name)

    def latest(self) -> tuple[np.ndarray | None, datetime | None, int]:
        with self._lock:
            return self._frame, self._frame_time, self._seq

    def _open(self) -> cv2.VideoCapture:
        return open_source(self._url, self.open_timeout_ms, self.read_timeout_ms)

    def run(self):
        delays = backoff_delays(self.reconnect_max)
        network = _is_network(self._url) or is_local_camera(self._url)
        announced = False  # "ulandi" hodisasi faqat haqiqiy ulanishda yuboriladi
        while not self._halt.is_set():
            cap = self._open()
            if not cap.isOpened():
                cap.release()
                self.attempts += 1
                self.last_error_at = time.monotonic()
                log.warning("camera %s: connect failed (attempt %d)", self.label, self.attempts)
                self._emit("on_connect_failed", self.attempts)
                self._halt.wait(next(delays))
                continue
            delays = backoff_delays(self.reconnect_max)
            if not announced:
                with self._lock:
                    self.connected = True
                announced = True
                log.info("camera %s: connected", self.label)
                self._emit("on_connect")
            # Fayl manbasi (sinov) uchun real vaqt tezligi
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_period = 0.0 if network else 1.0 / max(1.0, min(fps, 60.0))
            while not self._halt.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
                now = timezone.now()
                with self._lock:
                    self._frame = frame
                    self._frame_time = now
                    self._seq += 1
                if frame_period:
                    rest = frame_period - (time.monotonic() - t0)
                    if rest > 0:
                        self._halt.wait(rest)
            cap.release()
            if self._halt.is_set():
                break
            if not network:
                continue  # sinov fayli tugadi — boshidan qayta ijro (uzilish emas)
            with self._lock:
                self.connected = False
                self._frame = None
            announced = False
            self.attempts += 1
            self.last_error_at = time.monotonic()
            log.warning("camera %s: stream lost", self.label)
            self._emit("on_disconnect", self.attempts)
            self._halt.wait(next(delays))
        with self._lock:
            self.connected = False
            self._frame = None
