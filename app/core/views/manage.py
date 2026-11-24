"""Administrator sahifalari: o'quvchilar, yuz rasmlari, kamera tekshiruvi, audit, pilot."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Count, Q
from django.urls import reverse
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .. import crypto, services
from ..forms import SampleUploadForm, StudentImportForm
from ..models import (
    AttendanceRecord,
    AuditLog,
    FaceTemplate,
    RecognitionSettings,
    SchoolClass,
    Session,
    Student,
    User,
)
from .common import admin_required


def _class_id(value, classes):
    try:
        cid = int(value)
    except (TypeError, ValueError):
        return classes[0].pk if classes else None
    return cid if any(c.pk == cid for c in classes) else (classes[0].pk if classes else None)


def _roster(class_id, cfg):
    if not class_id:
        return []
    return [
        {"st": st, "templates": st.template_count, "enroll": services.enrollment_status(st, cfg)}
        for st in services.class_enrollment_summary(class_id)
    ]


@admin_required
def students(request):
    """O'quvchilar ro'yxati sinf bo'yicha: F.I.Sh., sinf, yuz rasmlari holati."""
    classes = list(SchoolClass.objects.all())
    class_id = _class_id(request.GET.get("class"), classes)
    cfg = RecognitionSettings.get()
    q = request.GET.get("q", "").strip()
    if q:  # yuqori paneldagi qidiruv: barcha sinflar bo'yicha F.I.Sh. yoki ID
        needle = q.casefold()
        rows = [
            r for c in classes for r in _roster(c.pk, cfg)
            if needle in r["st"].full_name.casefold() or needle in str(r["st"].student_code).casefold()
        ]
    else:
        rows = _roster(class_id, cfg)
    summary = {
        "total": len(rows),
        "ready": sum(1 for r in rows if r["enroll"] == "ready"),
        "partial": sum(1 for r in rows if r["enroll"] == "partial"),
        "none": sum(1 for r in rows if r["enroll"] == "none"),
    }
    return render(request, "manage/students.html", {
        "classes": classes, "class_id": class_id, "rows": rows, "cfg": cfg, "summary": summary, "q": q,
        "import_form": StudentImportForm(initial={"school_class": class_id}),
    })


@admin_required
def photos(request):
    """Yuz rasmlari: sinf → o'quvchi → rasm yuklash yoki kameradan olish (rasm o'quvchiga biriktiriladi)."""
    classes = list(SchoolClass.objects.all())
    st = None
    if request.GET.get("student"):
        st = get_object_or_404(Student.objects.select_related("school_class"), pk=request.GET["student"])
    class_id = st.school_class_id if st else _class_id(request.GET.get("class"), classes)
    cfg = RecognitionSettings.get()
    upload_form = SampleUploadForm()
    results = None

    if request.method == "POST" and st is not None:
        upload_form = SampleUploadForm(request.POST, request.FILES)
        if upload_form.is_valid():
            try:
                results = services.enroll_samples(st, upload_form.cleaned_data["images"], request.user)
            except services.SessionError as e:
                messages.error(request, str(e))
            else:
                ok = sum(1 for r in results if r.ok)
                (messages.success if ok else messages.warning)(
                    request, f"{st.full_name}: {ok} ta rasm qabul qilindi, {len(results) - ok} tasi rad etildi"
                )
        elif request.FILES == {} and request.META.get("CONTENT_LENGTH"):
            messages.error(request, "Fayl hajmi juda katta (10 MB gacha)")

    rows = _roster(class_id, cfg)
    templates = list(st.templates.defer("vector_encrypted")) if st else []  # yangilari birinchi
    next_st = None
    if st is not None:
        ids = [r["st"].pk for r in rows]
        pos = ids.index(st.pk) if st.pk in ids else -1
        # Keyingi rasmi yetarli bo'lmagan o'quvchi (ro'yxat bo'yicha aylanib)
        for r in rows[pos + 1:] + rows[:max(pos, 0)]:
            if r["enroll"] != "ready" and r["st"].pk != st.pk:
                next_st = r["st"]
                break

    return render(request, "manage/photos.html", {
        "classes": classes, "class_id": class_id, "rows": rows, "cfg": cfg,
        "st": st,
        "templates": templates,
        "new_ids": {r.template.pk for r in results or [] if r.template is not None and r.template.pk},
        "st_thumb": next((t.pk for t in templates if t.has_thumb), None),
        "enroll": services.enrollment_status(st, cfg) if st else None,
        "upload_form": upload_form,
        "results": results,
        "next_st": next_st,
    })


@admin_required
def student_detail(request, pk):
    """Eski manzil: endi «Yuz rasmlari» sahifasiga yo'naltiriladi."""
    return redirect(f"{reverse('photos')}?student={pk}")


@admin_required
def template_thumb(request, pk):
    """Andoza miniatyurasi: bazadan shifrlangan holda o'qiladi, faqat xotirada ochiladi, keshlanmaydi."""
    t = get_object_or_404(FaceTemplate.objects.only("thumb_encrypted"), pk=pk)
    if not t.thumb_encrypted:
        raise Http404
    resp = HttpResponse(crypto.decrypt_bytes(t.thumb_encrypted), content_type="image/jpeg")
    resp["Cache-Control"] = "private, no-store"
    return resp


@admin_required
@require_POST
def templates_delete(request, pk):
    st = get_object_or_404(Student, pk=pk)
    ids = request.POST.getlist("template_id")
    n = services.delete_templates(st, request.user, [int(i) for i in ids] if ids else None)
    messages.success(request, f"{n} ta rasm (andoza) oʻchirildi")
    return redirect(f"{reverse('photos')}?student={pk}")


SESSION_FILTERS = [
    ("", "Hammasi"),
    ("live", "Davom etayotgan"),
    ("ended", "Tasdiqlash kutilmoqda"),
    ("confirmed", "Tasdiqlangan"),
]


def _filtered_sessions(params):
    qs = Session.objects.select_related("school_class", "room", "teacher", "camera").annotate(
        n_total=Count("records", distinct=True),
        n_present=Count("records", filter=Q(records__status=AttendanceRecord.Status.PRESENT), distinct=True),
    )
    status = params.get("status", "")
    if status == "live":
        qs = qs.filter(status__in=Session.LIVE)
    elif status in (Session.Status.ENDED, Session.Status.CONFIRMED):
        qs = qs.filter(status=status)
    for key, field in (("class", "school_class_id"), ("teacher", "teacher_id")):
        if (params.get(key) or "").isdigit():
            qs = qs.filter(**{field: int(params[key])})
    for key, lookup in (("from", "started_at__date__gte"), ("to", "started_at__date__lte")):
        d = parse_date(params.get(key) or "")
        if d:
            qs = qs.filter(**{lookup: d})
    return qs.order_by("-started_at")


@admin_required
def manage_sessions(request):
    """Administrator: barcha sessiyalar — filtrlash, ko'rish, o'chirish."""
    services.close_expired_sessions()
    qs = _filtered_sessions(request.GET)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    all_s = Session.objects.all()
    stats = {
        "total": all_s.count(),
        "live": all_s.filter(status__in=Session.LIVE).count(),
        "ended": all_s.filter(status=Session.Status.ENDED).count(),
        "confirmed": all_s.filter(status=Session.Status.CONFIRMED).count(),
    }
    params = request.GET.copy()
    params.pop("page", None)
    status_params = params.copy()
    status_params.pop("status", None)
    return render(request, "manage/sessions.html", {
        "page": page,
        "stats": stats,
        "filters": SESSION_FILTERS,
        "status": request.GET.get("status", ""),
        "classes": SchoolClass.objects.all(),
        "teachers": User.objects.filter(role=User.Role.TEACHER).order_by("last_name", "first_name", "username"),
        "f": request.GET,
        "qs_keep": params.urlencode(),
        "qs_status": status_params.urlencode(),
        "has_filters": any(request.GET.get(k) for k in ("class", "teacher", "from", "to")),
    })


@admin_required
@require_POST
def sessions_delete(request):
    """1-qadam (confirm yo'q): tasdiqlash sahifasi. 2-qadam (confirm=1): o'chirish."""
    ids = [int(x) for x in request.POST.getlist("session_id") if x.isdigit()]
    back = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}) or not back.startswith("/"):
        back = reverse("manage_sessions")
    if not ids:
        messages.warning(request, "Oʻchirish uchun sessiya tanlanmagan")
        return redirect(back)
    if request.POST.get("confirm") != "1":
        sessions = list(_filtered_sessions({}).filter(pk__in=ids))
        return render(request, "manage/sessions_delete.html", {
            "sessions": [x for x in sessions if not x.is_live],
            "live": [x for x in sessions if x.is_live],
            "confirmed": sum(1 for x in sessions if x.status == Session.Status.CONFIRMED),
            "records": sum(x.n_total for x in sessions if not x.is_live),
            "back": back,
        })
    deleted, skipped = services.delete_sessions(request.user, ids)
    msg = f"{deleted} ta sessiya oʻchirildi"
    if skipped:
        msg += f"; {skipped} tasi davom etayotgani uchun oʻchirilmadi (avval yakunlang)"
    (messages.success if deleted else messages.warning)(request, msg)
    # O'chirilgan sessiya sahifasidan kelingan bo'lsa — ro'yxatga qaytiladi
    if any(f"/sessiyalar/{i}/" in back for i in ids):
        back = reverse("manage_sessions")
    return redirect(back)


@admin_required
def audit_log(request):
    qs = AuditLog.objects.select_related("actor", "session")
    if request.GET.get("after") == "1":
        qs = qs.filter(after_confirmation=True)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "manage/audit.html", {"page": page, "after": request.GET.get("after")})


@admin_required
def pilot(request):
    sessions = Session.objects.filter(status__in=[Session.Status.ENDED, Session.Status.CONFIRMED]).prefetch_related(
        "records", "intervals", "camera_events"
    )
    class_id = request.GET.get("class")
    if class_id:
        sessions = sessions.filter(school_class_id=class_id)
    m = services.pilot_metrics(sessions)
    return render(request, "manage/pilot.html", {
        "m": m, "classes": SchoolClass.objects.all(), "class_id": int(class_id) if class_id else None,
        "session_count": sessions.count(),
    })
