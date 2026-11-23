"""Kamera markazi: har bir kamera uchun bitta ulanish (FrameGrabber), bir nechta iste'molchi.

Kompyuter kamerasini bir vaqtda faqat bitta jarayon/oqim ocha oladi, RTSP kameralar esa
ortiqcha ulanishlarni yoqtirmaydi. Shuning uchun sessiya tahlili, jonli ko'rish va
o'rnatish tekshiruvi bitta grabber'dan foydalanadi. Iste'molchi qolmasa kamera yopiladi.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from .capture import FrameGrabber


@dataclass
class FaceMark:
    """Jonli ko'rishda yuz ustiga chiziladigan belgi (faqat xotirada)."""

    box: tuple[int, int, int, int]
    kind: str  # recognized / reliable / uncertain / unknown / low_quality / small
    label: str
    size: int
    quality_ok: bool


@dataclass
class CameraEntry:
    camera_id: int
    grabber: FrameGrabber
    users: dict[str, float | None] = field(default_factory=dict)  # kalit -> muddat (None = bo'shatilguncha)
    listeners: list = field(default_factory=list)
    # Sessiya tahlili natijasi (jonli ko'rish uchun)
    marks: list[FaceMark] = field(default_factory=list)
    marks_seq: int = -1
    marks_at: float = 0.0
    session_id: int | None = None
    # Jonli ko'rish uchun dvigatel (sessiya bo'lmaganda faqat aniqlash)
    engine: object | None = None
    engine_lock: threading.Lock = field(default_factory=threading.Lock)
    preview_cache: tuple | None = None  # (seq, jpeg bytes, headers)


class CameraHub:
    def __init__(self, reconnect_max_seconds: float = 30.0):
        self._lock = threading.Lock()
        self._entries: dict[int, CameraEntry] = {}
        self.reconnect_max = reconnect_max_seconds

    def acquire(self, camera_id: int, url: str, key: str, ttl: float | None = None, listener=None) -> CameraEntry:
        """Kamerani band qiladi (kerak bo'lsa ochadi). ttl berilsa — shuncha soniyadan keyin avtomatik bo'shaydi."""
        with self._lock:
            entry = self._entries.get(camera_id)
            if entry is not None and (not entry.grabber.is_alive() or entry.grabber.url != url):
                # Manzil o'zgargan yoki grabber to'xtagan — qayta ochiladi, tinglovchilar ko'chiriladi
                entry.grabber.stop()
                entry.grabber = self._new_grabber(camera_id, url)
                for li in entry.listeners:
                    entry.grabber.add_listener(li)
                entry.grabber.start()
            if entry is None:
                entry = CameraEntry(camera_id=camera_id, grabber=self._new_grabber(camera_id, url))
                self._entries[camera_id] = entry
                entry.grabber.start()
            entry.users[key] = (time.monotonic() + ttl) if ttl else None
            if listener is not None and listener not in entry.listeners:
                entry.listeners.append(listener)
        if listener is not None:
            entry.grabber.add_listener(listener)
        return entry

    def release(self, camera_id: int, key: str, listener=None):
        with self._lock:
            entry = self._entries.get(camera_id)
            if entry is None:
                return
            entry.users.pop(key, None)
            if listener is not None:
                if listener in entry.listeners:
                    entry.listeners.remove(listener)
                entry.grabber.remove_listener(listener)
        self.reap()

    def get(self, camera_id: int) -> CameraEntry | None:
        with self._lock:
            return self._entries.get(camera_id)

    def reap(self):
        """Muddati o'tgan iste'molchilarni olib tashlaydi, keraksiz kameralarni yopadi."""
        now = time.monotonic()
        to_stop = []
        with self._lock:
            for cid, entry in list(self._entries.items()):
                for k, exp in list(entry.users.items()):
                    if exp is not None and exp < now:
                        entry.users.pop(k, None)
                if not entry.users:
                    to_stop.append(self._entries.pop(cid))
        for entry in to_stop:
            entry.grabber.stop()
            entry.engine = None
            entry.preview_cache = None

    def stop_all(self):
        with self._lock:
            entries = list(self._entries.values())
            self._entries.clear()
        for e in entries:
            e.grabber.stop()
        for e in entries:
            e.grabber.join(timeout=10)

    def _new_grabber(self, camera_id: int, url: str) -> FrameGrabber:
        return FrameGrabber(url, label=str(camera_id), reconnect_max_seconds=self.reconnect_max)
