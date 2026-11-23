from cryptography.fernet import Fernet
from django.test import TestCase, override_settings
from django.urls import reverse

from core import crypto
from core.models import AuditLog, Camera, RecognitionSettings, Room, SchoolClass, Student, User

KEY = Fernet.generate_key().decode()


@override_settings(FIELD_ENCRYPTION_KEYS=[KEY], WORKER_PREVIEW_PORT=1)  # 1-port: worker yo'q holati
class ManageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        crypto.reset_cache()
        cls.admin = User.objects.create_user("admin", password="x" * 10, role=User.Role.ADMIN)
        cls.teacher = User.objects.create_user("t1", password="x" * 10)

    def setUp(self):
        crypto.reset_cache()
        self.client.force_login(self.admin)

    def test_room_camera_crud_with_encryption_and_audit(self):
        r = self.client.post(reverse("xonalar_create"), {"name": "202"})
        self.assertRedirects(r, reverse("xonalar_list"))
        room = Room.objects.get(name="202")
        r = self.client.post(reverse("kameralar_create"), {"room": room.pk, "name": "Old", "rtsp_url": "0",
                                                           "is_active": "on"})
        self.assertRedirects(r, reverse("cameras"))
        cam = Camera.objects.get()
        self.assertEqual(cam.rtsp_url, "0")
        self.assertEqual(cam.masked_url, "Kompyuter kamerasi #0")
        # Bo'sh manzil bilan tahrirlash eski manzilni saqlaydi
        self.client.post(reverse("kameralar_edit", args=[cam.pk]), {"room": room.pk, "name": "Yangi", "rtsp_url": ""})
        cam.refresh_from_db()
        self.assertEqual((cam.name, cam.rtsp_url, cam.is_active), ("Yangi", "0", False))
        # Noto'g'ri manzil rad etiladi
        r = self.client.post(reverse("kameralar_edit", args=[cam.pk]), {"room": room.pk, "name": "X", "rtsp_url": "ftp://x"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "rtsp://")
        # Kamerasi bor xonani o'chirib bo'lmaydi
        r = self.client.post(reverse("xonalar_delete", args=[room.pk]), follow=True)
        self.assertContains(r, "Oʻchirib boʻlmadi")
        self.assertTrue(Room.objects.filter(pk=room.pk).exists())
        actions = set(AuditLog.objects.values_list("action", flat=True))
        self.assertTrue({"xonalar_create", "kameralar_create", "kameralar_update"} <= actions)
        self.assertFalse(AuditLog.objects.filter(note__contains="rtsp://").exists())

    def test_user_create_and_self_protection(self):
        r = self.client.post(reverse("foydalanuvchilar_create"), {
            "username": "ustoz", "first_name": "A", "last_name": "B", "role": "teacher",
            "password1": "Kuchli-parol-2026", "password2": "Kuchli-parol-2026"})
        self.assertRedirects(r, reverse("foydalanuvchilar_list"))
        u = User.objects.get(username="ustoz")
        self.assertTrue(u.check_password("Kuchli-parol-2026"))
        self.assertFalse(u.is_staff)
        # Zaif parol rad etiladi
        r = self.client.post(reverse("foydalanuvchilar_create"), {
            "username": "u2", "role": "teacher", "password1": "123", "password2": "123"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(username="u2").exists())
        # O'zini adminlikdan chiqarish va o'chirish mumkin emas
        r = self.client.post(reverse("foydalanuvchilar_edit", args=[self.admin.pk]),
                             {"username": "admin", "role": "teacher", "is_active": "on"})
        self.assertContains(r, "administrator rolidan")
        self.client.post(reverse("foydalanuvchilar_delete", args=[self.admin.pk]))
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_assignment_and_student_import(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        cls = SchoolClass.objects.create(name="5-B", academic_year="2026-2027")
        room = Room.objects.create(name="1")
        r = self.client.post(reverse("biriktiruvlar_create"), {"teacher": self.teacher.pk, "school_class": cls.pk,
                                                               "room": room.pk})
        self.assertRedirects(r, reverse("biriktiruvlar_list"))
        r = self.client.post(reverse("biriktiruvlar_create"), {"teacher": self.teacher.pk, "school_class": cls.pk,
                                                               "room": room.pk})
        self.assertEqual(r.status_code, 200)  # takroriy biriktiruv rad etiladi
        csv = "Familiya;Ism;Otasining ismi\nAliyev;Ali;Valiyevich\nKarimova;Gulnoza\nToshmatov Eshmat\nAliyev;Ali;Valiyevich\n"
        self.client.post(reverse("students_import"), {"school_class": cls.pk,
                                                      "file": SimpleUploadedFile("s.csv", csv.encode("utf-8-sig"))})
        names = sorted(Student.objects.filter(school_class=cls).values_list("full_name", flat=True))
        self.assertEqual(names, ["Aliyev Ali Valiyevich", "Karimova Gulnoza", "Toshmatov Eshmat"])

    def test_settings_edit(self):
        data = {f.name: getattr(RecognitionSettings.get(), f.name)
                for f in RecognitionSettings._meta.fields if f.name not in ("id", "updated_at")}
        data["sim_threshold"] = 0.4
        r = self.client.post(reverse("settings_edit"), data)
        self.assertRedirects(r, reverse("settings_edit"))
        self.assertEqual(RecognitionSettings.get().sim_threshold, 0.4)
        self.assertTrue(AuditLog.objects.filter(action="settings_update", note__contains="sim_threshold").exists())

    def test_snapshot_without_worker_and_permissions(self):
        room = Room.objects.create(name="r")
        cam = Camera(room=room, name="c")
        cam.rtsp_url = "0"
        cam.save()
        r = self.client.get(reverse("camera_snapshot", args=[cam.pk]))
        self.assertEqual(r.status_code, 503)
        self.assertIn("worker", r.json()["error"])
        self.assertTrue(AuditLog.objects.filter(action="camera_view", object_id=str(cam.pk)).exists())
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("camera_snapshot", args=[cam.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("cameras")).status_code, 403)
