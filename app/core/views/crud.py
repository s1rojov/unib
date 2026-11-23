"""Boshqaruv bo'limi: ma'lumotnomalar uchun umumiy CRUD kontroller.

Har bir ma'lumotnoma (model + forma + ustunlar) bitta Resource sifatida tavsiflanadi;
ro'yxat, yaratish, tahrirlash va o'chirish sahifalari shu tavsifdan quriladi.
Barcha o'zgarishlar audit jurnaliga yoziladi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.http import urlencode
from django.views.decorators.http import require_POST

from .. import forms as f
from .. import services
from ..models import Camera, Room, SchoolClass, Student, TeacherAssignment, User
from .common import admin_required


def _yes(v):
    return "Ha" if v else "Yoʻq"


@dataclass
class Resource:
    key: str  # URL qismi
    model: type
    form: type
    title: str  # ko'plik
    title_one: str  # birlik (tushum kelishigi: "xonani")
    columns: list[tuple[str, Callable]]
    search: tuple[str, ...] = ()
    queryset: Callable | None = None
    edit_form: type | None = None
    list_url_name: str | None = None  # maxsus ro'yxat sahifasi bo'lsa
    after_save_url: Callable | None = None
    add_another: Callable | None = None  # «Saqlash va yana qo'shish»: keyingi forma uchun boshlang'ich qiymatlar
    delete_hint: str = ""
    section: str = "Maʼlumotnomalar"  # yon menyu bo'limi (sahifa yo'li uchun)
    form_kwargs: Callable | None = None
    extra_actions: list = field(default_factory=list)

    def qs(self):
        return self.queryset() if self.queryset else self.model.objects.all()

    @property
    def can_add_another(self) -> bool:
        # Shablon lambda'ni o'zi chaqirib yubormasligi uchun alohida bayroq
        return self.add_another is not None

    @property
    def list_url(self):
        return reverse(self.list_url_name or f"{self.key}_list")


RESOURCES: dict[str, Resource] = {}


def register(r: Resource):
    RESOURCES[r.key] = r
    return r


register(Resource(
    key="xonalar", model=Room, form=f.RoomForm, title="Xonalar", title_one="xona",
    columns=[("Nomi", lambda o: o.name), ("Kameralar", lambda o: o.cameras.count())],
    search=("name",),
    delete_hint="Sessiyalari yoki kameralari bor xonani oʻchirib boʻlmaydi.",
))
register(Resource(
    key="kameralar", model=Camera, form=f.CameraForm, title="Kameralar", title_one="kamera",
    columns=[("Nomi", lambda o: o.name), ("Xona", lambda o: o.room), ("Manzil", lambda o: o.masked_url),
             ("Holat", lambda o: o.get_status_display()), ("Faol", lambda o: _yes(o.is_active))],
    search=("name", "room__name"),
    queryset=lambda: Camera.objects.select_related("room"),
    list_url_name="cameras",
    delete_hint="Sessiyalari bor kamerani oʻchirib boʻlmaydi — uni nofaol qiling.",
))
register(Resource(
    key="sinflar", model=SchoolClass, form=f.SchoolClassForm, title="Sinflar", title_one="sinf",
    columns=[("Nomi", lambda o: o.name), ("Oʻquv yili", lambda o: o.academic_year),
             ("Oʻquvchilar", lambda o: o.students.filter(is_active=True).count())],
    search=("name", "academic_year"),
    add_another=lambda o: {"academic_year": o.academic_year},
    section="Oʻquvchilar bazasi",
    delete_hint="Oʻquvchilari yoki sessiyalari bor sinfni oʻchirib boʻlmaydi.",
))
register(Resource(
    key="oquvchilar", model=Student, form=f.StudentForm, title="Oʻquvchilar", title_one="oʻquvchi",
    columns=[("ID", lambda o: o.student_code), ("F.I.Sh.", lambda o: o.full_name), ("Sinf", lambda o: o.school_class),
             ("Faol", lambda o: _yes(o.is_active))],
    search=("student_code", "full_name"),
    queryset=lambda: Student.objects.select_related("school_class"),
    list_url_name="students",
    after_save_url=lambda o: f"{reverse('students')}?class={o.school_class_id}",
    add_another=lambda o: {"school_class": o.school_class_id},
    section="Oʻquvchilar bazasi",
    delete_hint="Davomat yozuvlari bor oʻquvchini oʻchirib boʻlmaydi — uni nofaol qiling. "
                "Oʻchirilganda yuz rasmlari (andozalari) ham oʻchadi.",
))
register(Resource(
    key="foydalanuvchilar", model=User, form=f.UserCreateForm, edit_form=f.UserEditForm,
    title="Foydalanuvchilar", title_one="foydalanuvchi",
    columns=[("Login", lambda o: o.username), ("F.I.Sh.", lambda o: o.get_full_name() or "—"),
             ("Rol", lambda o: o.get_role_display()), ("Faol", lambda o: _yes(o.is_active)),
             ("Oxirgi kirish", lambda o: o.last_login.strftime("%d.%m.%Y %H:%M") if o.last_login else "—")],
    search=("username", "first_name", "last_name"),
    queryset=lambda: User.objects.order_by("role", "username"),
    delete_hint="Sessiyalari bor oʻqituvchini oʻchirib boʻlmaydi — uni nofaol qiling (bloklash).",
))
register(Resource(
    key="biriktiruvlar", model=TeacherAssignment, form=f.AssignmentForm,
    title="Oʻqituvchi biriktiruvlari", title_one="biriktiruv",
    columns=[("Oʻqituvchi", lambda o: o.teacher.display_name), ("Sinf", lambda o: o.school_class),
             ("Xona", lambda o: o.room)],
    search=("teacher__username", "teacher__last_name", "school_class__name", "room__name"),
    queryset=lambda: TeacherAssignment.objects.select_related("teacher", "school_class", "room").order_by(
        "teacher__username", "school_class__name"),
))


def _resource(key) -> Resource:
    return RESOURCES[key]


def _form_class(r: Resource, editing: bool):
    return (r.edit_form or r.form) if editing else r.form


def _form_kwargs(r: Resource, request, editing):
    if editing and r.edit_form is f.UserEditForm:
        return {"current_user": request.user}
    return {}


@admin_required
def crud_list(request, key):
    r = _resource(key)
    qs = r.qs()
    q = request.GET.get("q", "").strip()
    if q and r.search:
        cond = Q()
        for fld in r.search:
            cond |= Q(**{f"{fld}__icontains": q})
        qs = qs.filter(cond)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    rows = [(o, [fn(o) for _, fn in r.columns]) for o in page]
    return render(request, "crud/list.html", {"r": r, "page": page, "rows": rows, "q": q,
                                              "headers": [h for h, _ in r.columns]})


@admin_required
def crud_create(request, key):
    r = _resource(key)
    form_cls = _form_class(r, False)
    initial = {k: v for k, v in request.GET.items() if k in form_cls.base_fields}
    form = form_cls(request.POST or None, initial=initial, **_form_kwargs(r, request, False))
    if request.method == "POST" and form.is_valid():
        obj = form.save()
        services.audit(request.user, f"{key}_create", obj, note=str(obj)[:200])
        messages.success(request, f"Yangi {r.title_one} qoʻshildi: {obj}")
        if r.add_another and "save_add" in request.POST:
            return redirect(f"{reverse(key + '_create')}?{urlencode(r.add_another(obj))}")
        return redirect(r.after_save_url(obj) if r.after_save_url else r.list_url)
    return render(request, "crud/form.html", {"r": r, "form": form, "obj": None})


@admin_required
def crud_edit(request, key, pk):
    r = _resource(key)
    obj = get_object_or_404(r.model, pk=pk)
    form = _form_class(r, True)(request.POST or None, instance=obj, **_form_kwargs(r, request, True))
    if request.method == "POST" and form.is_valid():
        changed = [fld for fld in form.changed_data if fld not in ("rtsp_url", "new_password")]
        secret_changed = [fld for fld in form.changed_data if fld in ("rtsp_url", "new_password")]
        obj = form.save()
        note = "oʻzgargan: " + ", ".join(changed + [f"{s} (yashirin)" for s in secret_changed]) if form.changed_data else ""
        services.audit(request.user, f"{key}_update", obj, note=note[:255])
        messages.success(request, "Saqlandi")
        return redirect(r.after_save_url(obj) if r.after_save_url else r.list_url)
    return render(request, "crud/form.html", {"r": r, "form": form, "obj": obj})


@admin_required
def crud_delete(request, key, pk):
    r = _resource(key)
    obj = get_object_or_404(r.model, pk=pk)
    if isinstance(obj, User) and obj.pk == request.user.pk:
        messages.error(request, "Oʻzingizni oʻchira olmaysiz")
        return redirect(r.list_url)
    if request.method == "POST":
        label = str(obj)
        try:
            obj_id = obj.pk
            obj.delete()
        except ProtectedError:
            messages.error(request, f"Oʻchirib boʻlmadi: bogʻliq yozuvlar bor. {r.delete_hint}")
            return redirect(r.list_url)
        obj.pk = obj_id
        services.audit(request.user, f"{key}_delete", obj, note=label[:200])
        messages.success(request, f"«{label}» oʻchirildi")
        return redirect(r.list_url)
    return render(request, "crud/confirm_delete.html", {"r": r, "obj": obj})


def urlpatterns():
    out = []
    for key, r in RESOURCES.items():
        base = f"boshqaruv/{key}/"
        if not r.list_url_name:
            out.append(path(base, crud_list, {"key": key}, name=f"{key}_list"))
        out += [
            path(base + "yangi/", crud_create, {"key": key}, name=f"{key}_create"),
            path(base + "<int:pk>/tahrir/", crud_edit, {"key": key}, name=f"{key}_edit"),
            path(base + "<int:pk>/ochirish/", crud_delete, {"key": key}, name=f"{key}_delete"),
        ]
    return out


@admin_required
def settings_edit(request):
    from ..models import RecognitionSettings

    obj = RecognitionSettings.get()
    form = f.RecognitionSettingsForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        changes = [f"{fld}: {form.initial.get(fld)} → {form.cleaned_data.get(fld)}" for fld in form.changed_data]
        form.save()
        services.audit(request.user, "settings_update", obj, note="; ".join(changes)[:255])
        messages.success(request, "Parametrlar saqlandi. Yangi sessiyalarda qoʻllanadi.")
        return redirect("settings_edit")
    return render(request, "manage/settings.html", {"form": form})


@admin_required
def manage_index(request):
    from ..models import AuditLog, FaceTemplate, Session

    counts = {
        "xonalar": Room.objects.count(),
        "kameralar": Camera.objects.count(),
        "sinflar": SchoolClass.objects.count(),
        "oquvchilar": Student.objects.filter(is_active=True).count(),
        "foydalanuvchilar": User.objects.filter(is_active=True).count(),
        "biriktiruvlar": TeacherAssignment.objects.count(),
        "andozali": FaceTemplate.objects.values("student").distinct().count(),
        "sessiyalar": Session.objects.count(),
        "audit": AuditLog.objects.count(),
    }
    return render(request, "manage/index.html", {"c": counts})


@admin_required
@require_POST
def students_import(request):
    import csv
    import io

    form = f.StudentImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "Sinf va CSV faylni tanlang")
        return redirect("students")
    cls = form.cleaned_data["school_class"]
    text = form.cleaned_data["file"].read().decode("utf-8-sig", errors="replace")
    sample = text[:2000]
    delim = ";" if sample.count(";") >= sample.count(",") else ","
    existing = set(Student.objects.filter(school_class=cls).values_list("full_name", flat=True))
    created = skipped = 0
    for row in csv.reader(io.StringIO(text), delimiter=delim):
        cells = [c.strip() for c in row if c.strip()]
        if not cells:
            continue
        if cells[0].lower().startswith(("familiya", "f.i.sh", "fish", "№", "#")):
            continue  # sarlavha qatori
        if len(cells) == 1:
            last, first, middle = Student.split_name(cells[0])
        else:
            last, first, middle = cells[0], cells[1], " ".join(cells[2:3])
        if not (last and first):
            continue
        st = Student(last_name=last[:80], first_name=first[:80], middle_name=middle[:80], school_class=cls)
        full = " ".join(p for p in (st.last_name, st.first_name, st.middle_name) if p)
        if full in existing:
            skipped += 1
            continue
        st.save()
        existing.add(st.full_name)
        created += 1
    services.audit(request.user, "students_import", cls, note=f"created={created} skipped={skipped}")
    messages.success(request, f"{created} ta oʻquvchi qoʻshildi"
                     + (f", {skipped} tasi bu sinfda allaqachon bor edi" if skipped else ""))
    return redirect(f"{reverse('students')}?class={cls.pk}")
