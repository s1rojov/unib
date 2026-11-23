"""Biznes-mantiq: sessiya hayot sikli, davomat belgilari, andozalar, hisobotlar.

Veb (views) va worker shu funksiyalardan foydalanadi; ruxsatlar shu yerda ham tekshiriladi.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.utils import timezone

from . import crypto
from .models import (
    AttendanceRecord,
    AuditLog,
    Camera,
    CameraEvent,
    FaceTemplate,
    RecognitionSettings,
    Session,
    Student,
    TeacherAssignment,
    User,
    VisibilityInterval,
)

log = logging.getLogger(__name__)
Mark = AttendanceRecord.Mark
CamStatus = AttendanceRecord.CameraStatus


# ---------------------------------------------------------------------------
# Audit (F-11)
# ---------------------------------------------------------------------------
def audit(actor, action, obj, *, field="", old="", new="", session=None, after_confirmation=False, note=""):
    AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk),
        session=session,
        field=field,
        old_value="" if old is None else str(old),
        new_value="" if new is None else str(new),
        after_confirmation=after_confirmation,
        note=note[:255],
    )


# ---------------------------------------------------------------------------
# Ruxsatlar (har bir so'rovda server tomonda)
# ---------------------------------------------------------------------------
def teacher_assigned(user: User, school_class_id: int, room_id: int | None = None) -> bool:
    qs = TeacherAssignment.objects.filter(teacher=user, school_class_id=school_class_id)
    if room_id is not None:
        qs = qs.filter(room_id=room_id)
    return qs.exists()


def can_view_session(user: User, session: Session) -> bool:
    if user.is_admin:
        return True
    return user.is_teacher and session.teacher_id == user.pk and teacher_assigned(
        user, session.school_class_id, session.room_id
    )


def can_edit_marks(user: User, session: Session) -> bool:
    """Tasdiqdan oldin — sessiya o'qituvchisi; tasdiqdan keyin — faqat administrator (audit bilan)."""
    if user.is_admin:
        return True
    return can_view_session(user, session) and session.status != Session.Status.CONFIRMED


def visible_sessions(user: User):
    qs = Session.objects.select_related("school_class", "room", "teacher", "camera")
    if user.is_admin:
        return qs
    assigned = TeacherAssignment.objects.filter(teacher=user).values_list("school_class_id", "room_id")
    cond = Q(pk__in=[])
    for class_id, room_id in assigned:
        cond |= Q(school_class_id=class_id, room_id=room_id)
    return qs.filter(teacher=user).filter(cond)


# ---------------------------------------------------------------------------
# Sessiya hayot sikli (F-03, F-07, F-09)
# ---------------------------------------------------------------------------
class SessionError(Exception):
    pass


def start_session(teacher: User, assignment: TeacherAssignment, pilot_blind: bool = False) -> Session:
    if not teacher.is_teacher or assignment.teacher_id != teacher.pk:
        raise PermissionDenied("Bu sinf va xona sizga biriktirilmagan")
    camera = assignment.room.active_camera()
    if camera is None:
        raise SessionError("Bu xonaga faol kamera biriktirilmagan")
    if not camera.rtsp_url_encrypted:
        raise SessionError("Kameraning RTSP manzili kiritilmagan")
    close_expired_sessions()
    cfg = RecognitionSettings.get()
    try:
        with transaction.atomic():
            session = Session.objects.create(
                school_class=assignment.school_class,
                room=assignment.room,
                camera=camera,
                teacher=teacher,
                status=Session.Status.OPEN,
                max_duration_minutes=cfg.session_max_minutes,
                pilot_blind=pilot_blind,
            )
            students = Student.objects.filter(school_class=assignment.school_class, is_active=True)
            eligible = set(
                FaceTemplate.objects.filter(student__in=students).values_list("student_id", flat=True)
            )
            AttendanceRecord.objects.bulk_create(
                [
                    AttendanceRecord(session=session, student=s, camera_eligible=s.pk in eligible)
                    for s in students
                ]
            )
    except IntegrityError:
        raise SessionError("Bu kamerada boshqa faol sessiya bor. Avval uni yakunlang.")
    audit(teacher, "session_start", session, session=session, note=f"camera={camera.pk}")
    log.info("session %s opened camera=%s class=%s", session.pk, camera.pk, session.school_class_id)
    return session


def delete_sessions(user: User, session_ids) -> tuple[int, int]:
    """Sessiyalarni butunlay o'chirish (faqat administrator).

    Davomat yozuvlari, ko'rinish oraliqlari, kamera hodisalari va kuzatuv belgilari birga o'chadi;
    audit jurnali saqlanadi (sessiya havolasi bo'shatiladi). Davom etayotgan sessiyalar o'chirilmaydi —
    worker ularga yozayotgan bo'ladi, avval yakunlash kerak. (o'chirilgan, o'tkazib yuborilgan) qaytaradi.
    """
    if not user.is_admin:
        raise PermissionDenied
    deleted = skipped = 0
    for pk in session_ids:
        with transaction.atomic():
            s = (Session.objects.select_for_update().select_related("school_class", "room", "teacher")
                 .filter(pk=pk).first())
            if s is None:
                continue
            if s.is_live:
                skipped += 1
                continue
            n_records = s.records.count()
            n_present = s.records.filter(status=AttendanceRecord.Status.PRESENT).count()
            note = (f"{s.school_class} · {s.room} · {timezone.localtime(s.started_at):%d.%m.%Y %H:%M} · "
                    f"{s.teacher.display_name} · {s.get_status_display()} · keldi {n_present}/{n_records}")
            audit(user, "session_delete", s, old=s.status, note=note)
            s.delete()
            deleted += 1
    return deleted, skipped


def end_session(session: Session, user: User | None, reason=Session.EndReason.TEACHER) -> Session:
    with transaction.atomic():
        s = Session.objects.select_for_update().get(pk=session.pk)
        if not s.is_live:
            return s
        s.status = Session.Status.ENDED
        s.ended_at = timezone.now()
        s.end_reason = reason
        s.auto_closed = reason == Session.EndReason.TIMEOUT
        s.save(update_fields=["status", "ended_at", "end_reason", "auto_closed"])
    audit(user, "session_end", s, session=s, new=reason)
    log.info("session %s ended reason=%s", s.pk, reason)
    return s


def close_expired_sessions() -> int:
    """F-09: maksimal davomiylikdan oshgan sessiyalar avtomatik yopiladi (tasdiqlanmagan)."""
    now = timezone.now()
    n = 0
    for s in Session.objects.filter(status__in=Session.LIVE).only("pk", "started_at", "max_duration_minutes"):
        if s.started_at + timedelta(minutes=s.max_duration_minutes) <= now:
            end_session(s, None, Session.EndReason.TIMEOUT)
            n += 1
    return n


def confirm_session(session: Session, user: User) -> Session:
    """Yakuniy davomatni tasdiqlash. Kamera aniqlagan, lekin belgilanmagan yozuvlar
    o'qituvchi tasdig'i bilan «Keldi», hal qilinmagan «Tekshirish kerak» — «Kelmadi»."""
    if not can_view_session(user, session):
        raise PermissionDenied
    with transaction.atomic():
        s = Session.objects.select_for_update().get(pk=session.pk)
        if s.status != Session.Status.ENDED:
            raise SessionError("Faqat yakunlangan sessiyani tasdiqlash mumkin")
        if s.camera_results_hidden:
            raise SessionError("Avval mustaqil yoʻqlamani yakunlang")
        now = timezone.now()
        for rec in s.records.select_for_update().filter(teacher_mark=""):
            rec.teacher_mark = Mark.PRESENT if rec.camera_status == CamStatus.RECOGNIZED else Mark.ABSENT
            rec.teacher_marked_at = now
            rec.teacher_marked_by = user
            rec.recompute()
            rec.save()
        s.status = Session.Status.CONFIRMED
        s.confirmed_at = now
        s.confirmed_by = user
        s.save(update_fields=["status", "confirmed_at", "confirmed_by"])
    audit(user, "session_confirm", s, session=s)
    return s


def set_mark(record: AttendanceRecord, user: User, value: str) -> AttendanceRecord:
    """O'qituvchi/administrator «Keldi»/«Kelmadi» belgisi (F-07). value='' — belgini olib tashlash."""
    if value not in ("", Mark.PRESENT, Mark.ABSENT):
        raise ValidationError("Notoʻgʻri qiymat")
    session = record.session
    if not can_edit_marks(user, session):
        raise PermissionDenied("Bu yozuvni oʻzgartirish huquqi yoʻq")
    if session.camera_results_hidden:
        raise SessionError("Avval mustaqil yoʻqlamani yakunlang")
    with transaction.atomic():
        s = Session.objects.select_for_update().get(pk=session.pk)
        rec = AttendanceRecord.objects.select_for_update().get(pk=record.pk)
        confirmed = s.status == Session.Status.CONFIRMED
        if confirmed and value == "":
            raise ValidationError("Tasdiqlangan sessiyada belgini olib tashlab boʻlmaydi")
        old = rec.teacher_mark
        if old == value:
            return rec
        rec.teacher_mark = value
        rec.teacher_marked_at = timezone.now() if value else None
        rec.teacher_marked_by = user if value else None
        rec.recompute()
        rec.save()
    audit(
        user, "mark", rec, field="teacher_mark", old=old or "—", new=value or "—", session=s,
        after_confirmation=confirmed, note=f"student={rec.student_id}",
    )
    return rec


def save_ground_truth(session: Session, user: User, marks: dict[int, str]) -> None:
    """Pilot: o'qituvchi kamera natijasini ko'rmasdan oldin mustaqil yo'qlama qiladi."""
    if not can_view_session(user, session):
        raise PermissionDenied
    if not session.pilot_blind or session.ground_truth_at is not None:
        raise SessionError("Mustaqil yoʻqlama bu sessiyada mavjud emas yoki allaqachon saqlangan")
    with transaction.atomic():
        recs = {r.pk: r for r in session.records.select_for_update()}
        missing = [pk for pk in recs if marks.get(pk) not in (Mark.PRESENT, Mark.ABSENT)]
        if missing:
            raise ValidationError("Barcha oʻquvchilar uchun belgi qoʻyilishi kerak")
        for pk, rec in recs.items():
            rec.ground_truth = marks[pk]
            rec.save(update_fields=["ground_truth"])
        Session.objects.filter(pk=session.pk).update(ground_truth_at=timezone.now())
    audit(user, "ground_truth", session, session=session)


def mark_displayed(session: Session, record_ids: list[int]) -> int:
    """Kechikish metrikasi uchun: natija brauzerda birinchi ko'rsatilgan vaqt."""
    return AttendanceRecord.objects.filter(
        session=session, pk__in=record_ids, camera_status=CamStatus.RECOGNIZED, displayed_at__isnull=True
    ).update(displayed_at=timezone.now())


# ---------------------------------------------------------------------------
# Worker yozuvlari (kamera). Sessiya qatori qulflanadi: yopilgan sessiyaga yozib bo'lmaydi.
# ---------------------------------------------------------------------------
def camera_mark_recognized(session_id: int, student_id: int, frame_time: datetime, score: float) -> bool:
    with transaction.atomic():
        live = Session.objects.select_for_update().filter(pk=session_id, status__in=Session.LIVE).exists()
        if not live:
            return False
        rec, _ = AttendanceRecord.objects.select_for_update().get_or_create(
            session_id=session_id, student_id=student_id, defaults={"camera_eligible": True}
        )
        if rec.camera_status == CamStatus.RECOGNIZED:
            return False  # sessiyada faqat bir marta hisoblanadi
        rec.camera_status = CamStatus.RECOGNIZED
        rec.camera_first_seen_at = frame_time
        rec.camera_score = round(float(score), 4)
        rec.camera_written_at = timezone.now()
        rec.recompute()
        rec.save()
    return True


def camera_mark_uncertain(session_id: int, student_id: int, frame_time: datetime, score: float) -> bool:
    with transaction.atomic():
        live = Session.objects.select_for_update().filter(pk=session_id, status__in=Session.LIVE).exists()
        if not live:
            return False
        rec = AttendanceRecord.objects.select_for_update().filter(
            session_id=session_id, student_id=student_id
        ).first()
        if rec is None or rec.camera_status == CamStatus.RECOGNIZED:
            return False
        if rec.uncertain_score is not None and rec.uncertain_score >= score:
            return False
        rec.camera_status = CamStatus.UNCERTAIN
        rec.uncertain_score = round(float(score), 4)
        rec.uncertain_seen_at = frame_time
        rec.recompute()
        rec.save()
    return True


def set_session_status(session_id: int, status: str) -> bool:
    """Worker holat o'tishlari: faqat jonli sessiyalar orasida (yakunlanganini qayta ochmaydi)."""
    return bool(
        Session.objects.filter(pk=session_id, status__in=Session.LIVE).exclude(status=status).update(status=status)
    )


def record_camera_event(camera_id: int, session_id: int | None, kind: str, attempt: int = 0):
    CameraEvent.objects.create(camera_id=camera_id, session_id=session_id, kind=kind, attempt=attempt)
    if kind in (CameraEvent.Kind.CONNECTED, CameraEvent.Kind.DISCONNECTED, CameraEvent.Kind.CONNECT_FAILED):
        status = Camera.Status.ONLINE if kind == CameraEvent.Kind.CONNECTED else Camera.Status.OFFLINE
        Camera.objects.filter(pk=camera_id).exclude(status=status).update(
            status=status, status_changed_at=timezone.now()
        )


def load_gallery_rows(school_class_id: int) -> tuple[list[int], np.ndarray]:
    """Faqat tanlangan sinfning faol o'quvchilari andozalari (yuz rasmlaridan)."""
    rows = FaceTemplate.objects.filter(
        student__school_class_id=school_class_id,
        student__is_active=True,
    ).values_list("student_id", "vector_encrypted")
    ids, vecs = [], []
    for sid, token in rows:
        try:
            vecs.append(crypto.decrypt_embedding(token))
            ids.append(sid)
        except Exception:
            log.warning("template decrypt failed for student=%s", sid)
    return ids, (np.stack(vecs) if vecs else np.zeros((0, 128), np.float32))


# ---------------------------------------------------------------------------
# Yuz andozalarini o'chirish
# ---------------------------------------------------------------------------
def delete_templates(student: Student, user: User, template_ids: list[int] | None = None) -> int:
    if not user.is_admin:
        raise PermissionDenied
    qs = FaceTemplate.objects.filter(student=student)
    if template_ids is not None:
        qs = qs.filter(pk__in=template_ids)
    n, _ = qs.delete()
    if not FaceTemplate.objects.filter(student=student).exists():
        # Rasmi qolmagan o'quvchi jonli sessiyalarda endi faqat qo'lda belgilanadi
        AttendanceRecord.objects.filter(
            student=student, session__status__in=Session.LIVE
        ).update(camera_eligible=False)
    audit(user, "templates_delete", student, new=str(n))
    return n


# ---------------------------------------------------------------------------
# Andoza yaratish (F-02)
# ---------------------------------------------------------------------------
@dataclass
class SampleResult:
    name: str
    ok: bool
    message: str
    quality: float | None = None
    template: FaceTemplate | None = None  # qabul qilingan rasmdan yaratilgan andoza


def enroll_samples(student: Student, files, user: User) -> list[SampleResult]:
    """Yuklangan namunalardan andoza yaratadi. Rasmlar faqat xotirada ishlanadi."""
    from django.conf import settings as dj

    from vision.engine import decode_image, face_thumbnail, with_shared_engine

    if not user.is_admin:
        raise PermissionDenied
    cfg = RecognitionSettings.get()
    existing = student.templates.count()
    results: list[SampleResult] = []
    to_save: list[FaceTemplate] = []

    def process(engine):
        engine.set_score_threshold(cfg.det_score_threshold)
        for f in files:
            name = getattr(f, "name", "rasm")
            if existing + len(to_save) >= cfg.enroll_max_samples:
                results.append(SampleResult(name, False, f"Maksimal namunalar soni ({cfg.enroll_max_samples}) toʻldi"))
                continue
            data = f.read()
            img = decode_image(data)
            del data
            if img is None:
                results.append(SampleResult(name, False, "Rasm oʻqilmadi (JPEG/PNG kerak)"))
                continue
            faces = engine.detect(img)
            if len(faces) != 1:
                results.append(SampleResult(
                    name, False, "Rasmda yuz topilmadi" if len(faces) == 0 else f"Rasmda {len(faces)} ta yuz bor — bitta boʻlishi kerak"
                ))
                continue
            df = engine.analyze(img, faces[0])
            q = df.quality
            reasons = q.reasons(cfg.enroll_min_face_px, cfg.enroll_min_blur_var, cfg.enroll_max_yaw_deg)
            if reasons:
                results.append(SampleResult(name, False, "Sifat yetarli emas: " + ", ".join(reasons)))
                continue
            score = quality_score(q, cfg)
            thumb = face_thumbnail(img, df.box)
            tpl = FaceTemplate(
                student=student,
                vector_encrypted=crypto.encrypt_embedding(df.feature),
                thumb_encrypted=crypto.encrypt_bytes(thumb) if thumb else None,
                model_version=dj.FACE_MODEL_VERSION,
                quality_score=score,
                face_size_px=int(q.size_px),
                created_by=user,
            )
            to_save.append(tpl)
            results.append(SampleResult(name, True, "Qabul qilindi", score, tpl))
            del img

    with_shared_engine(process)
    if to_save:
        FaceTemplate.objects.bulk_create(to_save)
        # Sessiya ketayotgan bo'lsa, o'quvchi darhol kamera bilan taniladigan bo'ladi
        AttendanceRecord.objects.filter(
            student=student, session__status__in=Session.LIVE
        ).update(camera_eligible=True)
        audit(user, "templates_add", student, new=str(len(to_save)))
    return results


def quality_score(q, cfg) -> float:
    """0..1 oralig'idagi soddalashtirilgan sifat balli (hisobot uchun)."""
    size = min(1.0, q.size_px / (cfg.enroll_min_face_px * 2.0))
    blur = min(1.0, q.blur_var / (cfg.enroll_min_blur_var * 3.0))
    yaw = max(0.0, 1.0 - q.yaw_deg / 90.0)
    return round(0.4 * size + 0.3 * blur + 0.3 * yaw, 3)


def enrollment_status(student: Student, cfg: RecognitionSettings | None = None) -> str:
    cfg = cfg or RecognitionSettings.get()
    n = getattr(student, "template_count", None)
    if n is None:
        n = student.templates.count()
    if n == 0:
        return "none"
    return "ready" if n >= cfg.enroll_min_samples else "partial"


# ---------------------------------------------------------------------------
# Hisobotlar (F-12, F-14, pilot metrikalari)
# ---------------------------------------------------------------------------
@dataclass
class SessionReport:
    session: Session
    total: int
    camera_detected: int
    teacher_present: int
    camera_rejected: int
    camera_missed_present: int
    final_present: int
    final_absent: int
    needs_review: int
    uncertain: int
    latency_p95: float | None
    latency_count: int
    analysed_seconds: float
    coverage: dict[int, float] = field(default_factory=dict)
    outages: list[dict] = field(default_factory=list)
    ground_truth: dict | None = None


def _percentile(values, p):
    if not values:
        return None
    return float(np.percentile(np.asarray(values, dtype=float), p))


def session_report(session: Session) -> SessionReport:
    recs = list(session.records.select_related("student").all())
    cam = [r for r in recs if r.camera_status == CamStatus.RECOGNIZED]
    teacher_present = [r for r in recs if r.teacher_mark == Mark.PRESENT]
    latencies = [
        (r.displayed_at - r.camera_first_seen_at).total_seconds()
        for r in cam if r.displayed_at and r.camera_first_seen_at
    ]
    end = session.ended_at or timezone.now()
    start = session.first_frame_at or session.started_at
    analysed = max(0.0, (end - start).total_seconds())
    coverage = {}
    if analysed > 0:
        totals: dict[int, float] = {}
        for iv in session.intervals.all():
            totals[iv.student_id] = totals.get(iv.student_id, 0.0) + iv.seconds
        coverage = {sid: min(1.0, sec / analysed) for sid, sec in totals.items()}
    rep = SessionReport(
        session=session,
        total=len(recs),
        camera_detected=len(cam),
        teacher_present=len(teacher_present),
        camera_rejected=sum(1 for r in cam if r.teacher_mark == Mark.ABSENT),
        camera_missed_present=sum(1 for r in teacher_present if r.camera_status != CamStatus.RECOGNIZED),
        final_present=sum(1 for r in recs if r.status == AttendanceRecord.Status.PRESENT),
        final_absent=sum(1 for r in recs if r.status == AttendanceRecord.Status.ABSENT),
        needs_review=sum(1 for r in recs if r.needs_review),
        uncertain=sum(1 for r in recs if r.camera_status == CamStatus.UNCERTAIN),
        latency_p95=_percentile(latencies, 95),
        latency_count=len(latencies),
        analysed_seconds=analysed,
        coverage=coverage,
        outages=_outages(session),
    )
    if any(r.ground_truth for r in recs):
        rep.ground_truth = ground_truth_metrics(recs)
    return rep


def _outages(session: Session) -> list[dict]:
    out, down_at = [], None
    for ev in session.camera_events.all():
        if ev.kind in (CameraEvent.Kind.DISCONNECTED, CameraEvent.Kind.CONNECT_FAILED) and down_at is None:
            down_at = ev.at
        elif ev.kind == CameraEvent.Kind.CONNECTED and down_at is not None:
            out.append({"from": down_at, "to": ev.at, "seconds": (ev.at - down_at).total_seconds()})
            down_at = None
    if down_at is not None:
        out.append({"from": down_at, "to": None, "seconds": None})
    return out


def ground_truth_metrics(recs) -> dict:
    """FP: kamera «keldi», lekin o'quvchi yo'q; FN: bor, lekin kamera topmadi."""
    gt = [r for r in recs if r.ground_truth]
    present = [r for r in gt if r.ground_truth == Mark.PRESENT]
    cam = [r for r in gt if r.camera_status == CamStatus.RECOGNIZED]
    tp = sum(1 for r in present if r.camera_status == CamStatus.RECOGNIZED)
    fn = len(present) - tp
    fp = sum(1 for r in cam if r.ground_truth == Mark.ABSENT)
    return {
        "students": len(gt),
        "present": len(present),
        "camera_detected": len(cam),
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tp_rate": tp / len(present) if present else None,
        "fn_rate": fn / len(present) if present else None,
        "fp_rate": fp / len(cam) if cam else None,
    }


def pilot_metrics(sessions) -> dict:
    """Barcha mustaqil yo'qlamali sessiyalar bo'yicha yig'ma pilot metrikalari."""
    agg = {"sessions": 0, "students": 0, "present": 0, "camera_detected": 0, "tp": 0, "fp": 0, "fn": 0,
           "sessions_with_fp": 0}
    latencies, coverages, recoveries = [], [], []
    for s in sessions:
        recs = list(s.records.all())
        if any(r.ground_truth for r in recs):
            m = ground_truth_metrics(recs)
            agg["sessions"] += 1
            for k in ("students", "present", "camera_detected", "tp", "fp", "fn"):
                agg[k] += m[k]
            agg["sessions_with_fp"] += 1 if m["fp"] else 0
        latencies += [
            (r.displayed_at - r.camera_first_seen_at).total_seconds()
            for r in recs if r.displayed_at and r.camera_first_seen_at
        ]
        rep = session_report(s)
        coverages += list(rep.coverage.values())
        recoveries += [o["seconds"] for o in rep.outages if o["seconds"] is not None]
    agg["tp_rate"] = agg["tp"] / agg["present"] if agg["present"] else None
    agg["fn_rate"] = agg["fn"] / agg["present"] if agg["present"] else None
    agg["fp_rate"] = agg["fp"] / agg["camera_detected"] if agg["camera_detected"] else None
    agg["latency_p95"] = _percentile(latencies, 95)
    agg["latency_count"] = len(latencies)
    agg["coverage_avg"] = float(np.mean(coverages)) if coverages else None
    agg["recovery_max"] = max(recoveries) if recoveries else None
    agg["recovery_count"] = len(recoveries)
    return agg


def class_enrollment_summary(school_class_id: int):
    return (
        Student.objects.filter(school_class_id=school_class_id)
        .annotate(
            template_count=Count("templates", distinct=True),
            # Ro'yxatda avatar sifatida eng sifatli rasm miniatyurasi
            thumb_id=Subquery(
                FaceTemplate.objects.filter(student=OuterRef("pk"), thumb_encrypted__isnull=False)
                .order_by("-quality_score").values("pk")[:1]
            ),
        )
        .order_by("full_name")
    )
