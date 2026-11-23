"""Tahlil jarayoni (worker). Veb-ilova bilan faqat PostgreSQL orqali aloqa qiladi.

Supervisor bazadan jonli sessiyalarni o'qiydi va har biriga SessionRunner oqimini
ishga tushiradi. Runner kameraga ulanadi, kadrlarni xotirada tahlil qiladi va faqat
natijani bazaga yozadi. Sessiya yakunlanganini ko'rgach to'xtaydi.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from datetime import timedelta

import numpy as np
from django.conf import settings
from django.db import close_old_connections, connections
from django.db.models import F
from django.utils import timezone

from core import services
from core.models import CameraCheck, CameraEvent, RecognitionSettings, Session, Student, VisibilityInterval

from .engine import FaceEngine
from .hub import CameraHub, FaceMark
from .matcher import (
    RELIABLE,
    UNCERTAIN,
    UNKNOWN,
    Candidate,
    ConfirmationTracker,
    Gallery,
    MatchParams,
    VisibilityTracker,
    decide_frame,
)
from .preview import PreviewServer

log = logging.getLogger("vision.worker")

HEARTBEAT_SECONDS = 2.0
GALLERY_RELOAD_SECONDS = 10.0
INTERVAL_FLUSH_SECONDS = 5.0


class SessionRunner(threading.Thread):
    def __init__(self, session_id: int, hub: CameraHub):
        super().__init__(name=f"session-{session_id}", daemon=True)
        self.session_id = session_id
        self.hub = hub
        self.hub_key = f"session-{session_id}"
        self.entry = None
        self.names: dict[int, str] = {}
        self.halt = threading.Event()
        # statistika
        self.frames = 0
        self.faces = 0
        self.unknown = 0
        self._proc_ms: list[float] = []
        self._fps_marks: list[float] = []
        self.uncertain_sent: dict[int, float] = {}

    # --- yordamchi DB yozuvlari (har bir oqim o'z ulanishidan foydalanadi) ---
    def _event(self, kind, attempt=0):
        if self.halt.is_set():
            return  # sessiya yopilgan — kechikkan hodisa yozilmaydi
        try:
            services.record_camera_event(self.camera_id, self.session_id, kind, attempt)
            if kind == CameraEvent.Kind.CONNECTED:
                services.set_session_status(self.session_id, Session.Status.ACTIVE)
            else:
                services.set_session_status(self.session_id, Session.Status.DISCONNECTED)
                Session.objects.filter(pk=self.session_id).update(reconnect_attempts=F("reconnect_attempts") + 1)
        except Exception:
            log.exception("session %s: event write failed", self.session_id)
        finally:
            connections.close_all()  # grabber oqimining ulanishi

    # FrameGrabber tinglovchisi
    def on_connect(self):
        self._event(CameraEvent.Kind.CONNECTED)

    def on_disconnect(self, attempt):
        self._event(CameraEvent.Kind.DISCONNECTED, attempt)

    def on_connect_failed(self, attempt):
        self._event(CameraEvent.Kind.CONNECT_FAILED, attempt)

    def run(self):
        entry = None
        try:
            s = Session.objects.select_related("camera").get(pk=self.session_id)
            if not s.is_live:
                return
            self.camera_id = s.camera_id
            self.class_id = s.school_class_id
            cfg = RecognitionSettings.get()
            self.params = MatchParams.from_settings(cfg)
            self.max_fps = max(0.5, cfg.max_fps)
            self.detect_max_width = cfg.detect_max_width
            services.set_session_status(self.session_id, Session.Status.CONNECTING)
            url = s.camera.rtsp_url

            engine = FaceEngine(det_score_threshold=cfg.det_score_threshold)
            self.gallery = self._load_gallery()
            self.confirm = ConfirmationTracker(self.params.confirm_frames, self.params.confirm_window_seconds)
            # Qayta ishga tushganda (worker restart) avval tasdiqlanganlar qayta hisoblanmaydi
            self.confirm.confirmed |= set(
                s.records.filter(camera_status="recognized").values_list("student_id", flat=True)
            )
            self.visibility = VisibilityTracker(self.params.visibility_gap_seconds)

            self.hub.reconnect_max = cfg.reconnect_max_seconds
            entry = self.entry = self.hub.acquire(self.camera_id, url, self.hub_key, listener=self)
            entry.session_id = self.session_id
            del url
            log.info("session %s: runner started camera=%s gallery=%d", self.session_id, self.camera_id, len(self.gallery))

            last_seq = 0
            next_hb = time.monotonic()
            next_gallery = time.monotonic() + GALLERY_RELOAD_SECONDS
            next_flush = time.monotonic() + INTERVAL_FLUSH_SECONDS
            min_period = 1.0 / self.max_fps
            last_proc = 0.0

            while not self.halt.is_set():
                now_m = time.monotonic()
                if now_m >= next_hb:
                    next_hb = now_m + HEARTBEAT_SECONDS
                    if not self._heartbeat():
                        self.halt.set()
                        break
                if now_m >= next_gallery:
                    next_gallery = now_m + GALLERY_RELOAD_SECONDS
                    self.gallery = self._load_gallery()
                if now_m >= next_flush:
                    next_flush = now_m + INTERVAL_FLUSH_SECONDS
                    self.visibility.expire(timezone.now())
                    self._flush_intervals()

                frame, frame_time, seq = entry.grabber.latest()
                if frame is None or seq == last_seq or (now_m - last_proc) < min_period:
                    self.halt.wait(0.01)
                    continue
                last_seq, last_proc = seq, now_m
                t0 = time.perf_counter()
                self._process(engine, frame, frame_time)
                del frame
                self._proc_ms.append((time.perf_counter() - t0) * 1000.0)
                self._fps_marks.append(time.monotonic())
        except Exception:
            log.exception("session %s: runner crashed", self.session_id)
        finally:
            if entry is not None:
                if entry.session_id == self.session_id:
                    entry.session_id = None
                    entry.marks = []
                self.hub.release(self.camera_id, self.hub_key, listener=self)
            try:
                if hasattr(self, "visibility"):
                    self.visibility.close_all()
                    self._flush_intervals()
                self._heartbeat(final=True)
            except Exception:
                log.exception("session %s: final flush failed", self.session_id)
            self.gallery = None  # andozalar xotiradan tushiriladi
            connections.close_all()
            log.info("session %s: runner stopped", self.session_id)

    def _load_gallery(self) -> Gallery:
        ids, vecs = services.load_gallery_rows(self.class_id)
        self.names = dict(Student.objects.filter(school_class_id=self.class_id).values_list("id", "full_name"))
        return Gallery(ids, vecs)

    def _process(self, engine: FaceEngine, frame: np.ndarray, frame_time):
        p = self.params
        faces = engine.detect(frame, self.detect_max_width)
        self.frames += 1
        self.faces += len(faces)
        candidates, boxes, marks = [], [], []
        # Juda kichik yuzlar uchun andoza hisoblanmaydi (CPU tejash) — ular baribir ishonchsiz
        skip_below = p.min_face_px * 0.6
        for row in faces:
            box = tuple(int(v) for v in row[:4])
            size = int(min(row[2], row[3]))
            if size < skip_below:
                marks.append(FaceMark(box, "small", f"{size}px kichik", size, False))
                continue
            df = engine.analyze(frame, row)
            sid1, s1, sid2, s2 = self.gallery.best_two(df.feature)
            q_ok = df.quality.passes(p.min_face_px, p.min_blur_var, p.max_yaw_deg)
            candidates.append(Candidate(q_ok, sid1, s1, sid2, s2))
            boxes.append((box, size, q_ok))
        decisions = decide_frame(candidates, p)
        for d in decisions:
            if d.kind == RELIABLE:
                self.visibility.observe(d.student_id, frame_time)
                if self.confirm.add(d.student_id, frame_time):
                    if services.camera_mark_recognized(self.session_id, d.student_id, frame_time, d.score):
                        log.info("session %s: student %s recognized score=%.3f", self.session_id, d.student_id, d.score)
            elif d.kind == UNCERTAIN:
                if d.student_id in self.confirm.confirmed:
                    continue
                prev = self.uncertain_sent.get(d.student_id, -1.0)
                if d.score > prev + 0.01:
                    self.uncertain_sent[d.student_id] = d.score
                    services.camera_mark_uncertain(self.session_id, d.student_id, frame_time, d.score)
            elif d.kind == UNKNOWN:
                self.unknown += 1
        # Jonli ko'rish uchun belgilar (tasdiqlash holati yangilangandan keyin)
        for d, (box, size, q_ok) in zip(decisions, boxes):
            marks.append(self._mark(d, box, size, q_ok))
        if self.entry is not None:
            self.entry.marks = marks
            self.entry.marks_at = time.monotonic()

    def _mark(self, d, box, size, q_ok) -> FaceMark:
        """Jonli ko'rish uchun yuz belgisi (faqat xotirada)."""
        name = self.names.get(d.student_id, "") if d.student_id else ""
        if d.kind == RELIABLE:
            kind = "recognized" if d.student_id in self.confirm.confirmed else "reliable"
            return FaceMark(box, kind, f"{name} {d.score:.2f}", size, q_ok)
        if d.kind == UNCERTAIN:
            return FaceMark(box, "uncertain", f"? {name} {d.score:.2f}", size, q_ok)
        if not q_ok:
            return FaceMark(box, "low_quality", f"{size}px sifat past", size, q_ok)
        return FaceMark(box, "unknown", "notanish", size, q_ok)

    def _flush_intervals(self):
        for iv in self.visibility.pending():
            if iv.db_id is None:
                obj = VisibilityInterval.objects.create(
                    session_id=self.session_id, student_id=iv.student_id,
                    started_at=iv.started_at, ended_at=iv.last_seen_at, frames=iv.frames,
                )
                iv.db_id = obj.pk
            else:
                VisibilityInterval.objects.filter(pk=iv.db_id).update(ended_at=iv.last_seen_at, frames=iv.frames)
            iv.dirty = False

    def _heartbeat(self, final=False) -> bool:
        """Statistikani yozadi va sessiya hali jonli ekanini tekshiradi."""
        now = timezone.now()
        mono = time.monotonic()
        self._fps_marks = [t for t in self._fps_marks if t >= mono - 10.0]
        span = (mono - self._fps_marks[0]) if len(self._fps_marks) > 1 else 0.0
        fps = (len(self._fps_marks) - 1) / span if span > 0 else 0.0
        proc = float(np.mean(self._proc_ms[-50:])) if self._proc_ms else 0.0
        self._proc_ms = self._proc_ms[-50:]
        update = dict(
            worker_heartbeat_at=now,
            frames_processed=F("frames_processed") + self.frames,
            faces_detected=F("faces_detected") + self.faces,
            unknown_faces=F("unknown_faces") + self.unknown,
            avg_fps=round(fps, 2),
            avg_process_ms=round(proc, 1),
        )
        if self.frames:
            update["last_frame_at"] = now
            Session.objects.filter(pk=self.session_id, first_frame_at__isnull=True).update(first_frame_at=now)
        self.frames = self.faces = self.unknown = 0
        Session.objects.filter(pk=self.session_id).update(**update)
        if final:
            return False
        status = Session.objects.filter(pk=self.session_id).values_list("status", flat=True).first()
        return status in Session.LIVE


def run_camera_check(check_id: int, hub: CameraHub):
    """F-15: kamera o'rnatish tekshiruvi — kadr saqlanmaydi, faqat yuzlar statistikasi."""
    key = f"check-{check_id}"
    chk = None
    try:
        chk = CameraCheck.objects.select_related("camera").get(pk=check_id)
        cfg = RecognitionSettings.get()
        entry = hub.acquire(chk.camera_id, chk.camera.rtsp_url, key, ttl=60)
        frame = None
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            frame, _, _ = entry.grabber.latest()
            if frame is not None:
                break
            time.sleep(0.2)
        if frame is None:
            chk.status = CameraCheck.Status.FAILED
            chk.result = {"error": "Kameradan kadr olinmadi"}
        else:
            engine = FaceEngine(det_score_threshold=cfg.det_score_threshold)
            h, w = frame.shape[:2]
            faces = engine.detect(frame, cfg.detect_max_width)
            items = []
            for row in faces:
                q = engine.analyze(frame, row, with_feature=False).quality
                items.append({
                    "x": int(row[0]), "y": int(row[1]),
                    "size": round(q.size_px), "blur": round(q.blur_var, 1), "yaw": round(q.yaw_deg, 1),
                    "ok": q.passes(cfg.min_face_px, cfg.min_blur_var, cfg.max_yaw_deg),
                })
            del frame
            items.sort(key=lambda i: i["y"])
            sizes = [i["size"] for i in items]
            chk.status = CameraCheck.Status.DONE
            chk.result = {
                "width": w, "height": h,
                "faces": len(items),
                "faces_ok": sum(1 for i in items if i["ok"]),
                "min_size": min(sizes) if sizes else None,
                "median_size": float(np.median(sizes)) if sizes else None,
                "min_face_px": cfg.min_face_px,
                "items": items,
            }
        chk.finished_at = timezone.now()
        chk.save(update_fields=["status", "result", "finished_at"])
    except Exception:
        log.exception("camera check %s failed", check_id)
        CameraCheck.objects.filter(pk=check_id).update(
            status=CameraCheck.Status.FAILED, result={"error": "Ichki xato"}, finished_at=timezone.now()
        )
    finally:
        if chk is not None:
            hub.release(chk.camera_id, key)
        connections.close_all()


class Supervisor:
    def __init__(self):
        self.hub = CameraHub()
        self.preview = None
        self.runners: dict[int, SessionRunner] = {}
        self.last_start: dict[int, float] = {}
        self.checks: dict[int, threading.Thread] = {}
        self.stopping = threading.Event()

    def install_signals(self):
        def _stop(signum, frame):
            log.info("signal %s: stopping", signum)
            self.stopping.set()

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)

    def tick(self):
        close_old_connections()
        services.close_expired_sessions()
        # Jonli sessiyalar
        live = set(Session.objects.filter(status__in=Session.LIVE).values_list("pk", flat=True))
        for sid in live:
            r = self.runners.get(sid)
            if r is None or not r.is_alive():
                if len(self._alive_runners()) >= max(1, settings.WORKER_THREADS):
                    log.warning("session %s: no free worker slot", sid)
                    continue
                if time.monotonic() - self.last_start.get(sid, -1e9) < 5.0:
                    continue  # yiqilgan runnerni darhol qayta ishga tushirmaslik
                self.last_start[sid] = time.monotonic()
                r = SessionRunner(sid, self.hub)
                self.runners[sid] = r
                r.start()
        for sid, r in list(self.runners.items()):
            if sid not in live:
                r.halt.set()
            if not r.is_alive():
                self.runners.pop(sid, None)
        # Kamera tekshiruvlari
        for chk_id in CameraCheck.objects.filter(status=CameraCheck.Status.PENDING).values_list("pk", flat=True)[:2]:
            if chk_id in self.checks:
                continue
            CameraCheck.objects.filter(pk=chk_id, status=CameraCheck.Status.PENDING).update(
                status=CameraCheck.Status.RUNNING
            )
            t = threading.Thread(target=run_camera_check, args=(chk_id, self.hub), daemon=True,
                                 name=f"check-{chk_id}")
            self.checks[chk_id] = t
            t.start()
        for chk_id, t in list(self.checks.items()):
            if not t.is_alive():
                self.checks.pop(chk_id, None)
        self.hub.reap()  # jonli ko'rish to'xtagan kameralarni yopish
        # Worker o'chib qolganda "running" bo'lib qolgan tekshiruvlar
        CameraCheck.objects.filter(
            status=CameraCheck.Status.RUNNING, requested_at__lt=timezone.now() - timedelta(minutes=5)
        ).exclude(pk__in=list(self.checks)).update(
            status=CameraCheck.Status.FAILED, result={"error": "Vaqt tugadi"}, finished_at=timezone.now()
        )

    def _alive_runners(self):
        return [r for r in self.runners.values() if r.is_alive()]

    def run_forever(self):
        log.info("worker started (threads=%d)", settings.WORKER_THREADS)
        if settings.CAMERA_PREVIEW_ENABLED:
            try:
                self.preview = PreviewServer(self.hub, settings.WORKER_PREVIEW_BIND, settings.WORKER_PREVIEW_PORT)
                self.preview.start()
            except OSError as e:
                log.error("preview server could not start: %s", e)
        while not self.stopping.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("supervisor tick failed")
                connections.close_all()
            self.stopping.wait(settings.WORKER_POLL_SECONDS)
        for r in self.runners.values():
            r.halt.set()
        for r in self.runners.values():
            r.join(timeout=20)
        if self.preview is not None:
            self.preview.stop()
        self.hub.stop_all()
        log.info("worker stopped")
