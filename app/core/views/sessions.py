import csv
import io
import json
from datetime import datetime, time as dtime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import services
from ..forms import ObservationUploadForm, StartSessionForm
from ..models import AttendanceRecord, Camera, AuditLog, ObserverAnnotation, RecognitionSettings, Session, Student
from .common import get_session_for

WORKER_STALE_SECONDS = 15


@login_required
def dashboard(request):
    user = request.user
    services.close_expired_sessions()
    visible = services.visible_sessions(user)
    today = visible.filter(started_at__date=timezone.localdate())
    today_records = AttendanceRecord.objects.filter(session__in=today)
    ctx = {
        "sessions": visible[:10],
        "today_count": today.count(),
        "pending_confirm": visible.filter(status=Session.Status.ENDED).count(),
        "today_total": today_records.count(),
        "today_present": today_records.filter(status=AttendanceRecord.Status.PRESENT).count(),
    }
    if user.is_teacher:
        ctx["start_form"] = StartSessionForm(teacher=user)
        ctx["live_sessions"] = services.visible_sessions(user).filter(status__in=Session.LIVE)
    if user.is_admin:
        ctx["cameras"] = Camera.objects.select_related("room").all()
        ctx["live_sessions"] = Session.objects.filter(status__in=Session.LIVE).select_related("school_class", "room")
        ctx["student_count"] = Student.objects.filter(is_active=True).count()
    return render(request, "dashboard.html", ctx)


@login_required
@require_POST
def session_start(request):
    if not request.user.is_teacher:
        raise PermissionDenied
    form = StartSessionForm(request.POST, teacher=request.user)
    if not form.is_valid():
        messages.error(request, "Sinf va xonani tanlang")
        return redirect("dashboard")
    try:
        s = services.start_session(request.user, form.cleaned_data["assignment"], form.cleaned_data["pilot_blind"])
    except services.SessionError as e:
        messages.error(request, str(e))
        return redirect("dashboard")
    return redirect("session_detail", pk=s.pk)


@login_required
def session_list(request):
    if request.user.is_admin:  # administrator uchun — boshqaruvli ro'yxat (filtrlar, o'chirish)
        q = request.GET.urlencode()
        return redirect(reverse("manage_sessions") + (f"?{q}" if q else ""))
    qs = services.visible_sessions(request.user)
    status = request.GET.get("status")
    if status:
        qs = qs.filter(status=status)
    return render(request, "sessions/list.html", {"sessions": qs[:200], "statuses": Session.Status.choices,
                                                   "status": status})


@login_required
def session_detail(request, pk):
    s = get_session_for(request.user, pk)
    ctx = {
        "s": s,
        "poll_ms": settings.UI_POLL_INTERVAL_MS,
        "can_edit": services.can_edit_marks(request.user, s),
        "preview_enabled": settings.CAMERA_PREVIEW_ENABLED,
    }
    if s.camera_results_hidden:
        ctx["records"] = s.records.select_related("student").order_by("student__full_name")
        return render(request, "sessions/ground_truth.html", ctx)
    return render(request, "sessions/detail.html", ctx)


@login_required
@require_GET
def session_camera(request, pk):
    """Sessiya kamerasidan jonli kadr: kim tanilyapti, kim yo'q — o'qituvchi o'z ko'zi bilan ko'radi.

    Faqat sessiyaga ruxsati bor foydalanuvchiga va faqat sessiya davom etayotganda.
    Mustaqil yo'qlama (pilot) tugaguncha ko'rsatilmaydi — ramkalarda ismlar bor.
    """
    from .cameras import proxy_snapshot

    s = get_session_for(request.user, pk)
    if not s.is_live:
        return JsonResponse({"error": "Sessiya yakunlangan — kamera tasviri oʻchirildi", "stop": True}, status=409)
    if s.camera_results_hidden:
        return JsonResponse({"error": "Mustaqil yoʻqlama tugaguncha kamera tasviri koʻrsatilmaydi", "stop": True},
                            status=403)
    return proxy_snapshot(request.user, s.camera)


def _record_json(r: AttendanceRecord, hidden: bool):
    d = {
        "id": r.pk,
        "student_id": r.student_id,
        "code": r.student.student_code,
        "name": r.student.full_name,
        "eligible": r.camera_eligible,
        "teacher_mark": r.teacher_mark,
    }
    if hidden:
        return d
    d.update({
        "status": r.status,
        "status_label": r.get_status_display(),
        "source": r.source,
        "source_label": r.get_source_display(),
        "camera_status": r.camera_status,
        "first_seen": timezone.localtime(r.camera_first_seen_at).strftime("%H:%M:%S") if r.camera_first_seen_at else None,
        "score": r.camera_score,
        "uncertain_score": r.uncertain_score,
        "displayed": r.displayed_at is not None,
    })
    return d


@login_required
@require_GET
def session_state(request, pk):
    s = get_session_for(request.user, pk)
    hidden = s.camera_results_hidden
    recs = list(s.records.select_related("student").order_by("student__full_name"))
    now = timezone.now()
    hb_age = (now - s.worker_heartbeat_at).total_seconds() if s.worker_heartbeat_at else None
    worker_ok = hb_age is not None and hb_age <= WORKER_STALE_SECONDS
    counts = {"total": len(recs)}
    if not hidden:
        counts.update({
            "camera": sum(1 for r in recs if r.camera_status == "recognized"),
            "present": sum(1 for r in recs if r.status == "present"),
            "absent": sum(1 for r in recs if r.status == "absent"),
            "review_unrecognized": sum(1 for r in recs if r.status == "review_unrecognized"),
            "review_uncertain": sum(1 for r in recs if r.status == "review_uncertain"),
        })
    return JsonResponse({
        "id": s.pk,
        "status": s.status,
        "status_label": s.status_label,
        "is_live": s.is_live,
        "hidden": hidden,
        "can_edit": services.can_edit_marks(request.user, s),
        "worker": {
            "ok": worker_ok,
            "heartbeat_age": round(hb_age, 1) if hb_age is not None else None,
            "fps": s.avg_fps,
            "process_ms": s.avg_process_ms,
            "frames": s.frames_processed,
            "unknown_faces": s.unknown_faces,
            "reconnects": s.reconnect_attempts,
        },
        "deadline": timezone.localtime(s.deadline).strftime("%H:%M"),
        "counts": counts,
        "records": [_record_json(r, hidden) for r in recs],
        "server_time": timezone.localtime(now).strftime("%H:%M:%S"),
    })


@login_required
@require_POST
def session_displayed(request, pk):
    s = get_session_for(request.user, pk)
    try:
        ids = [int(x) for x in json.loads(request.body or b"{}").get("ids", [])][:100]
    except (ValueError, TypeError, AttributeError):
        return HttpResponseBadRequest()
    return JsonResponse({"updated": services.mark_displayed(s, ids)})


@login_required
@require_POST
def record_mark(request, pk):
    rec = get_object_or_404(AttendanceRecord.objects.select_related("session"), pk=pk)
    get_session_for(request.user, rec.session_id)  # biriktiruv tekshiruvi
    try:
        value = json.loads(request.body or b"{}").get("value", "")
    except ValueError:
        return HttpResponseBadRequest()
    try:
        rec = services.set_mark(rec, request.user, value)
    except PermissionDenied:
        return JsonResponse({"error": "Bu yozuvni oʻzgartirish huquqi yoʻq"}, status=403)
    except (ValidationError, services.SessionError) as e:
        msg = e.messages[0] if hasattr(e, "messages") else str(e)
        return JsonResponse({"error": msg}, status=400)
    return JsonResponse({"ok": True, "record": _record_json(rec, False)})


@login_required
@require_POST
def session_end(request, pk):
    s = get_session_for(request.user, pk)
    reason = Session.EndReason.ADMIN if request.user.is_admin and s.teacher_id != request.user.pk else Session.EndReason.TEACHER
    services.end_session(s, request.user, reason)
    messages.success(request, "Sessiya yakunlandi: tahlil toʻxtatildi. Davomatni tekshirib, tasdiqlang.")
    return redirect("session_detail", pk=pk)


@login_required
@require_POST
def session_confirm(request, pk):
    s = get_session_for(request.user, pk)
    try:
        services.confirm_session(s, request.user)
    except services.SessionError as e:
        messages.error(request, str(e))
        return redirect("session_detail", pk=pk)
    messages.success(request, "Davomat tasdiqlandi")
    return redirect("session_report", pk=pk)


@login_required
@require_POST
def session_ground_truth(request, pk):
    s = get_session_for(request.user, pk)
    marks = {}
    for key, val in request.POST.items():
        if key.startswith("gt_"):
            try:
                marks[int(key[3:])] = val
            except ValueError:
                pass
    try:
        services.save_ground_truth(s, request.user, marks)
    except (ValidationError, services.SessionError) as e:
        messages.error(request, e.messages[0] if hasattr(e, "messages") else str(e))
    else:
        messages.success(request, "Mustaqil yoʻqlama saqlandi. Endi kamera natijalari koʻrsatiladi.")
    return redirect("session_detail", pk=pk)


@login_required
def session_report(request, pk):
    s = get_session_for(request.user, pk)
    if s.camera_results_hidden:
        messages.error(request, "Avval mustaqil yoʻqlamani yakunlang")
        return redirect("session_detail", pk=pk)
    rep = services.session_report(s)
    recs = s.records.select_related("student", "teacher_marked_by").order_by("student__full_name")
    rows = [(r, rep.coverage.get(r.student_id)) for r in recs]
    return render(request, "sessions/report.html", {
        "s": s, "rep": rep, "rows": rows,
        "events": s.camera_events.all(),
        "audit": AuditLog.objects.filter(session=s).select_related("actor")[:100],
    })


@login_required
def session_report_csv(request, pk):
    s = get_session_for(request.user, pk)
    if s.camera_results_hidden:
        raise PermissionDenied
    rep = services.session_report(s)
    buf = io.StringIO()
    buf.write("﻿")  # Excel uchun UTF-8 BOM
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Sessiya", s.pk])
    w.writerow(["Sinf", str(s.school_class)])
    w.writerow(["Xona", str(s.room)])
    w.writerow(["Oʻqituvchi", s.teacher.display_name])
    w.writerow(["Boshlanish", _fmt(s.started_at)])
    w.writerow(["Tugash", _fmt(s.ended_at)])
    w.writerow(["Holat", s.status_label])
    w.writerow(["Kamera aniqlaganlar", rep.camera_detected])
    w.writerow(["Oʻqituvchi tasdiqlagan kelganlar", rep.teacher_present])
    w.writerow(["Kamera aniqlab, oʻqituvchi rad etganlar", rep.camera_rejected])
    w.writerow(["Kamera topmagan kelganlar", rep.camera_missed_present])
    w.writerow([])
    w.writerow(["ID", "F.I.Sh.", "Yakuniy holat", "Manba", "Kamera natijasi", "Birinchi aniqlangan vaqt", "Ball",
                "Oʻqituvchi belgisi", "Koʻrinish qamrovi, %"])
    for r in s.records.select_related("student").order_by("student__full_name"):
        cov = rep.coverage.get(r.student_id)
        w.writerow([
            r.student.student_code, r.student.full_name, r.get_status_display(), r.get_source_display(),
            r.get_camera_status_display(), _fmt(r.camera_first_seen_at, "%H:%M:%S"),
            f"{r.camera_score:.3f}" if r.camera_score is not None else "",
            r.get_teacher_mark_display() if r.teacher_mark else "",
            f"{cov * 100:.0f}" if cov is not None else "",
        ])
    resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="davomat_sessiya_{s.pk}.csv"'
    return resp


def _fmt(dt, f="%d.%m.%Y %H:%M"):
    return timezone.localtime(dt).strftime(f) if dt else ""


# ---------------------------------------------------------------------------
# F-17: kuzatuvchi shabloni
# ---------------------------------------------------------------------------
@login_required
def session_observations(request, pk):
    s = get_session_for(request.user, pk)
    if request.GET.get("template"):
        buf = io.StringIO()
        buf.write("﻿")
        w = csv.writer(buf, delimiter=";")
        w.writerow(["vaqt (SS:DD:ss)", "oquvchi_id", "hodisa", "izoh"])
        w.writerow(["# hodisa kodlari: " + ", ".join(f"{k}={v}" for k, v in ObserverAnnotation.Event.choices)])
        for st in Student.objects.filter(attendance__session=s).order_by("full_name"):
            w.writerow(["", st.student_code, "", f"# {st.full_name}"])
        resp = HttpResponse(buf.getvalue(), content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = f'attachment; filename="kuzatuv_shablon_{s.pk}.csv"'
        return resp

    form = ObservationUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        created, errors = _import_observations(s, form.cleaned_data["file"], request.user)
        if created:
            messages.success(request, f"{created} ta belgi yuklandi")
        for e in errors[:10]:
            messages.error(request, e)
        return redirect("session_observations", pk=pk)

    gap = timedelta(seconds=RecognitionSettings.get().visibility_gap_seconds)
    intervals = {}
    for iv in s.intervals.all():
        intervals.setdefault(iv.student_id, []).append(iv)
    rows = []
    for a in s.annotations.select_related("student"):
        seen = any(iv.started_at - gap <= a.at <= iv.ended_at + gap for iv in intervals.get(a.student_id, []))
        rows.append((a, seen))
    seen_ratio = (sum(1 for _, x in rows if x) / len(rows)) if rows else None
    return render(request, "sessions/observations.html", {"s": s, "form": form, "rows": rows,
                                                          "seen_ratio": seen_ratio})


def _import_observations(s: Session, f, user):
    text = f.read().decode("utf-8-sig", errors="replace")
    students = {st.student_code: st for st in Student.objects.filter(attendance__session=s)}
    events = dict(ObserverAnnotation.Event.choices)
    day = timezone.localtime(s.started_at).date()
    tz = timezone.get_current_timezone()
    errors, objs = [], []
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=";"), start=1):
        if not row or not row[0].strip() or row[0].startswith("#") or i == 1:
            continue
        try:
            t = dtime.fromisoformat(row[0].strip())
            st = students[row[1].strip()]
            ev = row[2].strip()
            if ev not in events:
                raise KeyError(ev)
        except (ValueError, KeyError, IndexError):
            errors.append(f"{i}-qator oʻqilmadi")
            continue
        note = row[3].strip() if len(row) > 3 and not row[3].startswith("#") else ""
        objs.append(ObserverAnnotation(session=s, student=st, at=datetime.combine(day, t, tzinfo=tz), event=ev,
                                       note=note[:255], created_by=user))
    ObserverAnnotation.objects.bulk_create(objs)
    return len(objs), errors
