"""Ma'lumotlar modeli (TZ 4-bo'lim)."""
from datetime import timedelta
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.utils import timezone

from . import crypto


# ---------------------------------------------------------------------------
# Foydalanuvchi va rollar (F-13)
# ---------------------------------------------------------------------------
class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        TEACHER = "teacher", "Oʻqituvchi"

    role = models.CharField("rol", max_length=16, choices=Role.choices, default=Role.TEACHER)

    class Meta:
        verbose_name = "foydalanuvchi"
        verbose_name_plural = "foydalanuvchilar"

    def save(self, *args, **kwargs):
        if self._state.adding and self.is_superuser and self.role == self.Role.TEACHER:
            self.role = self.Role.ADMIN
        # Rol yagona manba: admin paneliga faqat administrator kiradi
        is_admin = self.role == self.Role.ADMIN
        self.is_staff = is_admin
        self.is_superuser = is_admin
        super().save(*args, **kwargs)

    @property
    def is_admin(self):
        return self.is_active and self.role == self.Role.ADMIN

    @property
    def is_teacher(self):
        return self.is_active and self.role == self.Role.TEACHER

    @property
    def display_name(self):
        return self.get_full_name() or self.username


# ---------------------------------------------------------------------------
# Xona, kamera, sinf, o'quvchi, biriktiruv (F-01)
# ---------------------------------------------------------------------------
class Room(models.Model):
    name = models.CharField("nomi", max_length=100, unique=True)

    class Meta:
        verbose_name = "xona"
        verbose_name_plural = "xonalar"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def active_camera(self):
        return self.cameras.filter(is_active=True).order_by("id").first()


class Camera(models.Model):
    class Status(models.TextChoices):
        UNKNOWN = "unknown", "Nomaʼlum"
        ONLINE = "online", "Ulangan"
        OFFLINE = "offline", "Uzilgan"

    room = models.ForeignKey(Room, verbose_name="xona", on_delete=models.PROTECT, related_name="cameras")
    name = models.CharField("nomi", max_length=100)
    # RTSP manzil rekvizitlari bilan birga shifrlangan holda saqlanadi
    rtsp_url_encrypted = models.TextField("RTSP manzil (shifrlangan)", blank=True, editable=False)
    is_active = models.BooleanField("faol", default=True)
    status = models.CharField("holat", max_length=16, choices=Status.choices, default=Status.UNKNOWN)
    status_changed_at = models.DateTimeField("holat vaqti", null=True, blank=True)

    class Meta:
        verbose_name = "kamera"
        verbose_name_plural = "kameralar"
        ordering = ["room__name", "name"]

    def __str__(self):
        return f"{self.name} ({self.room})"

    @property
    def rtsp_url(self) -> str:
        return crypto.decrypt_str(self.rtsp_url_encrypted)

    @rtsp_url.setter
    def rtsp_url(self, value: str):
        self.rtsp_url_encrypted = crypto.encrypt_str(value) if value else ""

    @property
    def masked_url(self) -> str:
        """Interfeys uchun: rekvizitlar va yo'l yashiriladi."""
        if not self.rtsp_url_encrypted:
            return "—"
        try:
            return mask_url(self.rtsp_url)
        except Exception:
            return "••••"


def mask_url(url: str) -> str:
    if url.strip().isdigit():
        return f"Kompyuter kamerasi #{url.strip()}"
    parts = urlsplit(url)
    if not parts.scheme or not parts.hostname:
        return "••••"
    host = parts.hostname + (f":{parts.port}" if parts.port else "")
    netloc = ("•••@" if parts.username or parts.password else "") + host
    return urlunsplit((parts.scheme, netloc, "/•••" if parts.path not in ("", "/") else "", "", ""))


class SchoolClass(models.Model):
    name = models.CharField("nomi", max_length=50)
    academic_year = models.CharField("oʻquv yili", max_length=20, help_text="masalan: 2026-2027")

    class Meta:
        verbose_name = "sinf"
        verbose_name_plural = "sinflar"
        ordering = ["-academic_year", "name"]
        constraints = [models.UniqueConstraint(fields=["name", "academic_year"], name="uniq_class_year")]

    def __str__(self):
        return f"{self.name} ({self.academic_year})"


class Student(models.Model):
    last_name = models.CharField("familiya", max_length=80)
    first_name = models.CharField("ism", max_length=80)
    middle_name = models.CharField("otasining ismi", max_length=80, blank=True)
    # Familiya + ism + otasining ismi; saqlashda avtomatik yig'iladi (hisobot, CSV, qidiruv uchun)
    full_name = models.CharField("F.I.Sh.", max_length=245, editable=False)
    student_code = models.CharField(
        "ID raqami", max_length=32, unique=True, blank=True,
        help_text="Ixtiyoriy. Boʻsh qoldirilsa avtomatik beriladi",
    )
    school_class = models.ForeignKey(
        SchoolClass, verbose_name="sinf", on_delete=models.PROTECT, related_name="students"
    )
    is_active = models.BooleanField("faol", default=True)

    class Meta:
        verbose_name = "oʻquvchi"
        verbose_name_plural = "oʻquvchilar"
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} [{self.student_code}]"

    @staticmethod
    def split_name(full_name: str) -> tuple[str, str, str]:
        """«Aliyev Vali Karimovich» → (familiya, ism, otasining ismi)."""
        parts = (full_name or "").split()
        return (parts[0] if parts else "", parts[1] if len(parts) > 1 else "", " ".join(parts[2:]))

    def save(self, *args, **kwargs):
        if not (self.last_name or self.first_name) and self.full_name:
            self.last_name, self.first_name, self.middle_name = self.split_name(self.full_name)
        self.last_name, self.first_name, self.middle_name = (
            self.last_name.strip(), self.first_name.strip(), self.middle_name.strip()
        )
        self.full_name = " ".join(p for p in (self.last_name, self.first_name, self.middle_name) if p)
        if not self.student_code:
            self.student_code = self._next_code()
        super().save(*args, **kwargs)

    @classmethod
    def _next_code(cls) -> str:
        n = cls.objects.count() + 1
        while cls.objects.filter(student_code=f"S{n:05d}").exists():
            n += 1
        return f"S{n:05d}"


class TeacherAssignment(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="oʻqituvchi",
        on_delete=models.CASCADE,
        related_name="assignments",
        limit_choices_to={"role": User.Role.TEACHER},
    )
    school_class = models.ForeignKey(SchoolClass, verbose_name="sinf", on_delete=models.CASCADE)
    room = models.ForeignKey(Room, verbose_name="xona", on_delete=models.CASCADE)

    class Meta:
        verbose_name = "oʻqituvchi biriktiruvi"
        verbose_name_plural = "oʻqituvchi biriktiruvlari"
        constraints = [
            models.UniqueConstraint(fields=["teacher", "school_class", "room"], name="uniq_assignment")
        ]

    def __str__(self):
        return f"{self.teacher} → {self.school_class} / {self.room}"


# ---------------------------------------------------------------------------
# Rozilik (F-10, F-16) va yuz andozalari (F-02)
# Rozilik 20.11.2026 dan interfeysda ham, tanishda ham talab qilinmaydi (buyurtmachi qarori):
# o'quvchining yuz rasmi bo'lsa — kamera taniydi. Model eski yozuvlarni saqlash uchun qoldirilgan.
# ---------------------------------------------------------------------------
class Consent(models.Model):
    class Purpose(models.TextChoices):
        ATTENDANCE = "attendance", "Davomat (yuzni tanish)"
        BEHAVIOR = "behavior", "Xatti-harakat tahlili"

    class Status(models.TextChoices):
        ACTIVE = "active", "Amalda"
        WITHDRAWN = "withdrawn", "Qaytarib olingan"

    class Document(models.TextChoices):
        PAPER = "paper", "Qogʻoz"
        SCAN = "scan", "Skan"
        ELECTRONIC = "electronic", "Elektron"

    student = models.ForeignKey(Student, verbose_name="oʻquvchi", on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField("maqsad", max_length=16, choices=Purpose.choices)
    given_by = models.CharField("kim bergan (F.I.Sh.)", max_length=200)
    relation = models.CharField("aloqasi", max_length=50, help_text="ota, ona, qonuniy vakil…")
    document_type = models.CharField("hujjat turi", max_length=16, choices=Document.choices)
    document_ref = models.CharField("hujjat raqami", max_length=100, blank=True)
    given_on = models.DateField("sana")
    status = models.CharField("holat", max_length=16, choices=Status.choices, default=Status.ACTIVE)
    withdrawn_on = models.DateTimeField("qaytarilgan sana", null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="qayd etgan", on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "rozilik"
        verbose_name_plural = "roziliklar"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "purpose"], condition=Q(status="active"), name="uniq_active_consent"
            )
        ]

    def __str__(self):
        return f"{self.student_id}: {self.get_purpose_display()} ({self.get_status_display()})"


class FaceTemplate(models.Model):
    student = models.ForeignKey(Student, verbose_name="oʻquvchi", on_delete=models.CASCADE, related_name="templates")
    vector_encrypted = models.BinaryField("vektor (shifrlangan)")
    # Yuzning kichik kesimi (160×160 JPEG), shifrlangan — administrator qaysi rasm biriktirilganini ko'rishi uchun
    thumb_encrypted = models.BinaryField("miniatyura (shifrlangan)", null=True, blank=True, editable=False)
    model_version = models.CharField("model versiyasi", max_length=64)
    quality_score = models.FloatField("sifat balli")
    face_size_px = models.PositiveIntegerField("yuz oʻlchami (px)")
    created_at = models.DateTimeField("sana", auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )

    class Meta:
        verbose_name = "yuz andozasi"
        verbose_name_plural = "yuz andozalari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"andoza #{self.pk} (oʻquvchi {self.student_id})"

    @property
    def has_thumb(self) -> bool:
        return bool(self.thumb_encrypted)


# ---------------------------------------------------------------------------
# Tanish parametrlari (pilotda kalibrlanadi)
# ---------------------------------------------------------------------------
class RecognitionSettings(models.Model):
    # Moslikni tasdiqlash qoidasi (TZ 4-bo'lim)
    sim_threshold = models.FloatField(
        "T — kosinus oʻxshashlik chegarasi", default=0.363, help_text="SFace boshlangʻich qiymati 0,363"
    )
    margin_delta = models.FloatField("Δ — eng yaqin ikki nomzod farqi", default=0.05)
    confirm_frames = models.PositiveIntegerField("N — tasdiqlovchi kadrlar soni", default=3)
    confirm_window_seconds = models.PositiveIntegerField("Tasdiq vaqt oynasi (s)", default=10)
    uncertain_threshold = models.FloatField(
        "Noaniq nomzod chegarasi", default=0.30, help_text="Bundan yuqori, lekin qoidadan oʻtmagan moslik «Noaniq»"
    )
    # Kadrdagi yuz sifati
    det_score_threshold = models.FloatField("YuNet ishonch chegarasi", default=0.8)
    min_face_px = models.PositiveIntegerField("Minimal yuz oʻlchami (px)", default=40)
    min_blur_var = models.FloatField("Minimal tiniqlik (Laplas dispersiyasi)", default=25.0)
    max_yaw_deg = models.FloatField("Maksimal bosh burilishi (°, taxminiy)", default=40.0)
    # Andoza yaratish (F-02)
    enroll_min_samples = models.PositiveIntegerField("Andoza: minimal namunalar soni", default=3)
    enroll_max_samples = models.PositiveIntegerField("Andoza: maksimal namunalar soni", default=10)
    enroll_min_face_px = models.PositiveIntegerField("Andoza: minimal yuz oʻlchami (px)", default=80)
    enroll_min_blur_var = models.FloatField("Andoza: minimal tiniqlik", default=60.0)
    enroll_max_yaw_deg = models.FloatField("Andoza: maksimal bosh burilishi (°)", default=35.0)
    # Ishlash
    max_fps = models.FloatField("Tahlil tezligi chegarasi (kadr/s)", default=8.0)
    detect_max_width = models.PositiveIntegerField("Aniqlash uchun maksimal kadr kengligi (px)", default=1920)
    visibility_gap_seconds = models.PositiveIntegerField(
        "Koʻrinish oraligʻi uzilishi (s)", default=10, help_text="F-14: shundan uzoq koʻrinmasa yangi oraliq ochiladi"
    )
    session_max_minutes = models.PositiveIntegerField("Sessiya maksimal davomiyligi (daq)", default=120)
    reconnect_max_seconds = models.PositiveIntegerField("Qayta ulanish maksimal oraligʻi (s)", default=30)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "tanish parametrlari"
        verbose_name_plural = "tanish parametrlari"

    def __str__(self):
        return "Tanish parametrlari"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ---------------------------------------------------------------------------
# Sessiya va davomat
# ---------------------------------------------------------------------------
class Session(models.Model):
    class Status(models.TextChoices):
        OPEN = "open", "Ochiq"
        CONNECTING = "connecting", "Ulanmoqda"
        ACTIVE = "active", "Faol"
        DISCONNECTED = "disconnected", "Uzilgan"
        ENDED = "ended", "Yakunlangan"
        CONFIRMED = "confirmed", "Tasdiqlangan"

    LIVE = (Status.OPEN, Status.CONNECTING, Status.ACTIVE, Status.DISCONNECTED)

    class EndReason(models.TextChoices):
        TEACHER = "teacher", "Oʻqituvchi yakunladi"
        TIMEOUT = "timeout", "Maksimal davomiylik tugadi"
        ADMIN = "admin", "Administrator yakunladi"

    school_class = models.ForeignKey(SchoolClass, verbose_name="sinf", on_delete=models.PROTECT)
    room = models.ForeignKey(Room, verbose_name="xona", on_delete=models.PROTECT)
    camera = models.ForeignKey(Camera, verbose_name="kamera", on_delete=models.PROTECT)
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="oʻqituvchi", on_delete=models.PROTECT)
    status = models.CharField("holat", max_length=16, choices=Status.choices, default=Status.OPEN)
    started_at = models.DateTimeField("boshlanish", default=timezone.now)
    ended_at = models.DateTimeField("tugash", null=True, blank=True)
    end_reason = models.CharField("yakunlash sababi", max_length=16, choices=EndReason.choices, blank=True)
    confirmed_at = models.DateTimeField("tasdiq vaqti", null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    auto_closed = models.BooleanField("avtomatik yopilgan", default=False)
    max_duration_minutes = models.PositiveIntegerField("maksimal davomiylik (daq)", default=120)
    # Pilot: haqiqiy davomat kamera natijasini ko'rmasdan oldin qayd etiladi
    pilot_blind = models.BooleanField("mustaqil yoʻqlama (pilot)", default=False)
    ground_truth_at = models.DateTimeField("mustaqil yoʻqlama vaqti", null=True, blank=True)
    # Worker holati va statistikasi
    worker_heartbeat_at = models.DateTimeField(null=True, blank=True)
    first_frame_at = models.DateTimeField(null=True, blank=True)
    last_frame_at = models.DateTimeField(null=True, blank=True)
    frames_processed = models.PositiveIntegerField(default=0)
    faces_detected = models.PositiveIntegerField(default=0)
    unknown_faces = models.PositiveIntegerField("notanish yuzlar (kadrlar boʻyicha)", default=0)
    avg_fps = models.FloatField(default=0)
    avg_process_ms = models.FloatField(default=0)
    reconnect_attempts = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "sessiya"
        verbose_name_plural = "sessiyalar"
        ordering = ["-started_at"]
        constraints = [
            # F-03: bitta kamerada bir vaqtda faqat bitta faol sessiya
            models.UniqueConstraint(
                fields=["camera"],
                condition=Q(status__in=["open", "connecting", "active", "disconnected"]),
                name="one_live_session_per_camera",
            )
        ]

    def __str__(self):
        return f"Sessiya #{self.pk} — {self.school_class}"

    @property
    def is_live(self):
        return self.status in self.LIVE

    @property
    def deadline(self):
        return self.started_at + timedelta(minutes=self.max_duration_minutes)

    @property
    def status_label(self):
        if self.status == self.Status.ENDED and self.auto_closed:
            return "Tasdiqlanmagan (avtomatik yopilgan)"
        if self.status == self.Status.ENDED:
            return "Yakunlangan (tasdiqlanmagan)"
        return self.get_status_display()

    @property
    def camera_results_hidden(self):
        """Mustaqil yo'qlama tugaguncha kamera natijasi ko'rsatilmaydi."""
        return self.pilot_blind and self.ground_truth_at is None


class AttendanceRecord(models.Model):
    class CameraStatus(models.TextChoices):
        NONE = "none", "Aniqlanmagan"
        UNCERTAIN = "uncertain", "Noaniq (ehtimoliy nomzod)"
        RECOGNIZED = "recognized", "Aniqlangan"

    class Mark(models.TextChoices):
        PRESENT = "present", "Keldi"
        ABSENT = "absent", "Kelmadi"

    class Status(models.TextChoices):
        PRESENT = "present", "Keldi"
        ABSENT = "absent", "Kelmadi"
        REVIEW_UNRECOGNIZED = "review_unrecognized", "Tekshirish kerak: aniqlanmagan"
        REVIEW_UNCERTAIN = "review_uncertain", "Tekshirish kerak: noaniq"

    class Source(models.TextChoices):
        NONE = "", "—"
        CAMERA = "camera", "Kamera"
        TEACHER = "teacher", "Oʻqituvchi"
        CAMERA_TEACHER = "camera_teacher", "Kamera + oʻqituvchi"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="attendance")
    status = models.CharField("holat", max_length=24, choices=Status.choices, default=Status.REVIEW_UNRECOGNIZED)
    source = models.CharField("manba", max_length=16, choices=Source.choices, default="", blank=True)
    camera_eligible = models.BooleanField("kamera bilan tanish mumkin", default=False)
    # Kamera natijasi
    camera_status = models.CharField(max_length=16, choices=CameraStatus.choices, default=CameraStatus.NONE)
    camera_first_seen_at = models.DateTimeField("birinchi aniqlangan vaqt (kadr)", null=True, blank=True)
    camera_written_at = models.DateTimeField("natija yozilgan vaqt", null=True, blank=True)
    camera_score = models.FloatField("ball", null=True, blank=True)
    uncertain_score = models.FloatField(null=True, blank=True)
    uncertain_seen_at = models.DateTimeField(null=True, blank=True)
    displayed_at = models.DateTimeField("ekranda koʻrsatilgan vaqt", null=True, blank=True)
    # O'qituvchi belgisi
    teacher_mark = models.CharField(max_length=16, choices=Mark.choices, blank=True, default="")
    teacher_marked_at = models.DateTimeField(null=True, blank=True)
    teacher_marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Pilot: mustaqil qo'lda yo'qlama (ground truth)
    ground_truth = models.CharField(max_length=16, choices=Mark.choices, blank=True, default="")

    class Meta:
        verbose_name = "davomat yozuvi"
        verbose_name_plural = "davomat yozuvlari"
        constraints = [
            # Bir o'quvchi sessiyada faqat bir marta hisoblanadi
            models.UniqueConstraint(fields=["session", "student"], name="uniq_attendance_session_student")
        ]

    def recompute(self):
        """Yakuniy holat va manbani kamera va o'qituvchi belgisidan hisoblaydi (F-08)."""
        cam = self.camera_status == self.CameraStatus.RECOGNIZED
        if self.teacher_mark == self.Mark.PRESENT:
            self.status = self.Status.PRESENT
            self.source = self.Source.CAMERA_TEACHER if cam else self.Source.TEACHER
        elif self.teacher_mark == self.Mark.ABSENT:
            self.status = self.Status.ABSENT
            self.source = self.Source.TEACHER
        elif cam:
            self.status = self.Status.PRESENT
            self.source = self.Source.CAMERA
        else:
            self.status = (
                self.Status.REVIEW_UNCERTAIN
                if self.camera_status == self.CameraStatus.UNCERTAIN
                else self.Status.REVIEW_UNRECOGNIZED
            )
            self.source = self.Source.NONE

    @property
    def needs_review(self):
        return self.status in (self.Status.REVIEW_UNCERTAIN, self.Status.REVIEW_UNRECOGNIZED)


class VisibilityInterval(models.Model):
    """F-14: o'quvchi tanilgan vaqt oraliqlari (ko'rinish xronologiyasi)."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="intervals")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="+")
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField()
    frames = models.PositiveIntegerField("tasdiqlovchi kadrlar soni", default=0)

    class Meta:
        verbose_name = "koʻrinish oraligʻi"
        verbose_name_plural = "koʻrinish oraliqlari"
        ordering = ["started_at"]
        indexes = [models.Index(fields=["session", "student"])]

    @property
    def seconds(self):
        return max(0.0, (self.ended_at - self.started_at).total_seconds())


class CameraEvent(models.Model):
    class Kind(models.TextChoices):
        CONNECTED = "connected", "Ulandi"
        DISCONNECTED = "disconnected", "Uzildi"
        CONNECT_FAILED = "connect_failed", "Ulanib boʻlmadi"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="camera_events", null=True)
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="events")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    at = models.DateTimeField(default=timezone.now)
    attempt = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "kamera hodisasi"
        verbose_name_plural = "kamera hodisalari"
        ordering = ["at"]


class AuditLog(models.Model):
    """F-11: kim, qachon, qaysi yozuv, eski/yangi qiymat."""

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    at = models.DateTimeField(default=timezone.now, db_index=True)
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    session = models.ForeignKey(Session, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    field = models.CharField(max_length=64, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    after_confirmation = models.BooleanField("tasdiqdan keyin", default=False)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "audit yozuvi"
        verbose_name_plural = "audit jurnali"
        ordering = ["-at"]


class CameraCheck(models.Model):
    """F-15: kamera o'rnatish tekshiruvi. Kadr saqlanmaydi, faqat statistika."""

    class Status(models.TextChoices):
        PENDING = "pending", "Navbatda"
        RUNNING = "running", "Bajarilmoqda"
        DONE = "done", "Tayyor"
        FAILED = "failed", "Xato"

    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="checks")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    requested_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    result = models.JSONField(default=dict, blank=True)
    note = models.CharField("izoh (masalan, qatorlar)", max_length=255, blank=True)

    class Meta:
        verbose_name = "kamera tekshiruvi"
        verbose_name_plural = "kamera tekshiruvlari"
        ordering = ["-requested_at"]


class ObserverAnnotation(models.Model):
    """F-17: kuzatuvchining qo'lda belgilashi (2-bosqich modelini tekshirish uchun)."""

    class Event(models.TextChoices):
        LOOK_BOARD = "look_board", "Doskaga/oʻqituvchiga qaradi"
        HAND_RAISE = "hand_raise", "Qoʻl koʻtardi"
        GO_BOARD = "go_board", "Doskaga chiqdi"
        HEAD_DOWN = "head_down", "Boshini partaga qoʻydi"
        DISTRACTED = "distracted", "Chalgʻidi"
        OTHER = "other", "Boshqa"

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="annotations")
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="+")
    at = models.DateTimeField("vaqt")
    event = models.CharField("hodisa", max_length=16, choices=Event.choices)
    note = models.CharField("izoh", max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        verbose_name = "kuzatuvchi belgisi"
        verbose_name_plural = "kuzatuvchi belgilari"
        ordering = ["at"]
