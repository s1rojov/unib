"""Kameralar nazorati: holat, jonli ko'rish va o'rnatish tekshiruvi (administrator).

Jonli kadr proksisi (`proxy_snapshot`) o'qituvchining sessiya oynasida ham ishlatiladi
(faqat o'z faol sessiyasi kamerasi uchun, ruxsat sessions.session_camera da tekshiriladi).

Jonli kadr worker'dan (xotiradan) olinadi va brauzerga uzatiladi; hech qayerda saqlanmaydi.
Har bir administratorning kamerani ko'rgani audit jurnaliga yoziladi (10 daqiqada bir marta).
"""
import json
import urllib.error
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .. import services
from ..models import AuditLog, Camera, CameraCheck, RecognitionSettings, Session
from .common import admin_required

PASS_HEADERS = ("X-Faces", "X-Faces-Ok", "X-Recognized", "X-Min-Size", "X-Median-Size", "X-Width", "X-Height",
                "X-Min-Face-Px", "X-Source", "X-Session", "X-Frame-Time")


@admin_required
def cameras(request):
    cams = list(Camera.objects.select_related("room").order_by("room__name", "name"))
    live = {
        s.camera_id: s
        for s in Session.objects.filter(status__in=Session.LIVE).select_related("school_class", "teacher")
        .annotate(n_total=Count("records"), n_cam=Count("records", filter=Q(records__camera_status="recognized")))
    }
    checks = CameraCheck.objects.select_related("camera", "requested_by")[:20]
    return render(request, "manage/cameras.html", {
        "tiles": [(c, live.get(c.pk)) for c in cams],
        "checks": checks,
        "cfg": RecognitionSettings.get(),
        "pending": any(c.status in ("pending", "running") for c in checks),
        "preview_enabled": settings.CAMERA_PREVIEW_ENABLED,
    })


@admin_required
@require_POST
def camera_check(request, pk):
    cam = get_object_or_404(Camera, pk=pk)
    CameraCheck.objects.create(camera=cam, requested_by=request.user, note=request.POST.get("note", "")[:255])
    messages.info(request, f"«{cam.name}» tekshiruvi navbatga qoʻyildi — natija bir necha soniyada chiqadi")
    return redirect("cameras")


@admin_required
@require_GET
def camera_snapshot(request, pk):
    """Kameradan so'nggi kadr (yuzlar belgilangan holda). Worker ishlamasa — 503."""
    cam = get_object_or_404(Camera, pk=pk)
    return proxy_snapshot(request.user, cam)


def proxy_snapshot(user, cam: Camera) -> HttpResponse:
    """Worker'dan so'nggi kadrni (yuz ramkalari bilan) olib beradi; kadr hech qayerda saqlanmaydi."""
    if not settings.CAMERA_PREVIEW_ENABLED:
        return JsonResponse({"error": "Jonli koʻrish oʻchirilgan", "stop": True}, status=403)
    _audit_view(user, cam)
    from vision.preview import preview_token

    url = f"http://{settings.WORKER_PREVIEW_HOST}:{settings.WORKER_PREVIEW_PORT}/snapshot/{cam.pk}.jpg"
    req = urllib.request.Request(url, headers={"X-Preview-Token": preview_token()})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read()
            out = HttpResponse(body, content_type="image/jpeg")
            for h in PASS_HEADERS:
                if resp.headers.get(h) is not None:
                    out[h] = resp.headers[h]
    except urllib.error.HTTPError as e:
        try:
            data = json.loads(e.read() or b"{}")
        except ValueError:
            data = {}
        if e.code == 503:
            msg = ("Kameraga ulanib boʻlmayapti (band yoki oʻchiq) — qayta urinilmoqda"
                   if data.get("state") == "failed" else "Kameraga ulanmoqda…")
            return JsonResponse({"error": msg, "state": data.get("state"),
                                 "attempts": data.get("attempts", 0)}, status=503)
        return JsonResponse({"error": "Kadr olinmadi"}, status=502)
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        return JsonResponse({"error": "Tahlil jarayoni (worker) ishlamayapti — uni ishga tushiring"}, status=503)
    out["Cache-Control"] = "no-store"
    return out


def _audit_view(user, cam):
    recent = AuditLog.objects.filter(
        actor=user, action="camera_view", object_id=str(cam.pk), at__gte=timezone.now() - timedelta(minutes=10)
    ).exists()
    if not recent:
        services.audit(user, "camera_view", cam, note="jonli koʻrish")
