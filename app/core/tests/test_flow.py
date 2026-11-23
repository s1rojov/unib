import json
from datetime import timedelta

import numpy as np
from cryptography.fernet import Fernet
from django.core.exceptions import PermissionDenied
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core import crypto, services
from core.models import (
    AttendanceRecord,
    AuditLog,
    Camera,
    FaceTemplate,
    Room,
    SchoolClass,
    Session,
    Student,
    TeacherAssignment,
    User,
)

KEY = Fernet.generate_key().decode()


@override_settings(FIELD_ENCRYPTION_KEYS=[KEY])
class FlowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        crypto.reset_cache()
        cls.admin = User.objects.create_user("admin", password="x" * 10, role=User.Role.ADMIN)
        cls.teacher = User.objects.create_user("t1", password="x" * 10)
        cls.other = User.objects.create_user("t2", password="x" * 10)
        cls.room = Room.objects.create(name="101")
        cam = Camera(room=cls.room, name="cam")
        cam.rtsp_url = "rtsp://user:secret@10.0.0.5:554/stream1"
        cam.save()
        cls.camera = cam
        cls.cls = SchoolClass.objects.create(name="7-A", academic_year="2026-2027")
        cls.students = [
            Student.objects.create(student_code=f"S{i}", full_name=f"Oʻquvchi {i}", school_class=cls.cls)
            for i in range(4)
        ]
        cls.assignment = TeacherAssignment.objects.create(teacher=cls.teacher, school_class=cls.cls, room=cls.room)
        # S0 va S1: yuz andozasi bor (rozilik talab qilinmaydi)
        for st in cls.students[:2]:
            FaceTemplate.objects.create(student=st, vector_encrypted=crypto.encrypt_embedding(np.ones(128)),
                                        model_version="t", quality_score=1, face_size_px=100)

    def setUp(self):
        crypto.reset_cache()

    def start(self, **kw):
        return services.start_session(self.teacher, self.assignment, **kw)

    # --- F-01 / shifrlash ---
    def test_rtsp_encrypted_and_masked(self):
        self.assertNotIn("secret", self.camera.rtsp_url_encrypted)
        self.assertEqual(Camera.objects.get(pk=self.camera.pk).rtsp_url, "rtsp://user:secret@10.0.0.5:554/stream1")
        self.assertNotIn("secret", self.camera.masked_url)
        self.assertNotIn("user", self.camera.masked_url)

    def test_template_encrypted_roundtrip(self):
        t = FaceTemplate.objects.first()
        self.assertTrue(np.allclose(crypto.decrypt_embedding(t.vector_encrypted), np.ones(128)))

    # --- F-03 ---
    def test_start_creates_records_and_one_session_per_camera(self):
        s = self.start()
        self.assertEqual(s.records.count(), 4)
        self.assertEqual(s.records.filter(camera_eligible=True).count(), 2)
        with self.assertRaises(services.SessionError):
            self.start()
        services.end_session(s, self.teacher)
        self.start()  # yakunlangandan keyin yangi sessiya mumkin

    def test_unassigned_teacher_cannot_start_or_view(self):
        with self.assertRaises(PermissionDenied):
            services.start_session(self.other, self.assignment)
        s = self.start()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("session_detail", args=[s.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("session_state", args=[s.pk])).status_code, 403)

    def test_assignment_removed_revokes_access(self):
        s = self.start()
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("session_state", args=[s.pk])).status_code, 200)
        TeacherAssignment.objects.all().delete()
        self.assertEqual(self.client.get(reverse("session_state", args=[s.pk])).status_code, 403)

    # --- F-04 / qabul mezoni 2 va 5 ---
    def test_camera_counts_once_and_cannot_write_after_close(self):
        s = self.start()
        st = self.students[0]
        now = timezone.now()
        self.assertTrue(services.camera_mark_recognized(s.pk, st.pk, now, 0.7))
        self.assertFalse(services.camera_mark_recognized(s.pk, st.pk, now, 0.9))
        rec = AttendanceRecord.objects.get(session=s, student=st)
        self.assertEqual((rec.status, rec.source, rec.camera_score), ("present", "camera", 0.7))
        self.assertEqual(AttendanceRecord.objects.filter(session=s, student=st).count(), 1)
        services.end_session(s, self.teacher)
        self.assertFalse(services.camera_mark_recognized(s.pk, self.students[1].pk, now, 0.8))
        self.assertFalse(services.camera_mark_uncertain(s.pk, self.students[1].pk, now, 0.32))
        self.assertEqual(AttendanceRecord.objects.get(session=s, student=self.students[1]).camera_status, "none")

    def test_worker_status_cannot_reopen_ended(self):
        s = self.start()
        services.end_session(s, self.teacher)
        self.assertFalse(services.set_session_status(s.pk, Session.Status.ACTIVE))
        self.assertEqual(Session.objects.get(pk=s.pk).status, "ended")

    def test_uncertain_status(self):
        s = self.start()
        services.camera_mark_uncertain(s.pk, self.students[1].pk, timezone.now(), 0.33)
        rec = AttendanceRecord.objects.get(session=s, student=self.students[1])
        self.assertEqual(rec.status, "review_uncertain")

    # --- F-07, F-08, F-11, F-12 ---
    def test_marks_confirm_and_report(self):
        s = self.start()
        now = timezone.now()
        s0, s1, s2, s3 = self.students
        services.camera_mark_recognized(s.pk, s0.pk, now, 0.7)  # kamera, tasdiq bilan -> camera_teacher
        services.camera_mark_recognized(s.pk, s1.pk, now, 0.6)  # kamera, o'qituvchi rad etadi
        r = lambda st: AttendanceRecord.objects.get(session=s, student=st)  # noqa: E731
        services.set_mark(r(s1), self.teacher, "absent")
        services.set_mark(r(s2), self.teacher, "present")  # kamera topmagan kelgan
        with self.assertRaises(services.SessionError):
            services.confirm_session(s, self.teacher)  # avval yakunlash kerak
        services.end_session(s, self.teacher)
        services.confirm_session(s, self.teacher)
        self.assertEqual((r(s0).status, r(s0).source), ("present", "camera_teacher"))
        self.assertEqual((r(s1).status, r(s1).source), ("absent", "teacher"))
        self.assertEqual((r(s2).status, r(s2).source), ("present", "teacher"))
        self.assertEqual(r(s3).status, "absent")  # hal qilinmagan -> kelmadi
        rep = services.session_report(Session.objects.get(pk=s.pk))
        self.assertEqual(
            (rep.camera_detected, rep.teacher_present, rep.camera_rejected, rep.camera_missed_present), (2, 2, 1, 1)
        )
        # Tasdiqdan keyin o'qituvchi o'zgartira olmaydi, administrator — audit bilan
        with self.assertRaises(PermissionDenied):
            services.set_mark(r(s3), self.teacher, "present")
        services.set_mark(r(s3), self.admin, "present")
        log = AuditLog.objects.filter(action="mark", after_confirmation=True).get()
        self.assertEqual((log.actor, log.old_value, log.new_value), (self.admin, "absent", "present"))

    def test_csv_export(self):
        s = self.start()
        services.end_session(s, self.teacher)
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse("session_report_csv", args=[s.pk]))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Kamera aniqlaganlar", body)
        self.assertIn("Oʻquvchi 0", body)

    # --- F-09 ---
    def test_expired_session_auto_closed(self):
        s = self.start()
        Session.objects.filter(pk=s.pk).update(started_at=timezone.now() - timedelta(minutes=500))
        self.assertEqual(services.close_expired_sessions(), 1)
        s.refresh_from_db()
        self.assertEqual((s.status, s.auto_closed, s.end_reason), ("ended", True, "timeout"))
        self.assertIn("Tasdiqlanmagan", s.status_label)

    # --- Yuz rasmlari: rasm bor — taniladi, yo'q — faqat qo'lda ---
    def test_photos_define_camera_eligibility(self):
        s = self.start()
        rec = {r.student_id: r.camera_eligible for r in s.records.all()}
        self.assertTrue(rec[self.students[0].pk] and rec[self.students[1].pk])
        self.assertFalse(rec[self.students[2].pk] or rec[self.students[3].pk])
        ids, _ = services.load_gallery_rows(self.cls.pk)
        self.assertEqual(sorted(ids), sorted([self.students[0].pk, self.students[1].pk]))

    def test_delete_photos_removes_from_gallery(self):
        s = self.start()
        st = self.students[0]
        self.assertEqual(services.delete_templates(st, self.admin), 1)
        self.assertFalse(AttendanceRecord.objects.get(session=s, student=st).camera_eligible)
        ids, _ = services.load_gallery_rows(self.cls.pk)
        self.assertNotIn(st.pk, ids)
        self.assertIn(self.students[1].pk, ids)

    def test_student_name_parts_and_auto_code(self):
        st = Student.objects.create(last_name=" Aliyev ", first_name="Vali", middle_name="Karimovich",
                                    school_class=self.cls)
        self.assertEqual(st.full_name, "Aliyev Vali Karimovich")
        self.assertTrue(st.student_code)
        st2 = Student.objects.create(last_name="Karimova", first_name="Gulnoza", school_class=self.cls)
        self.assertNotEqual(st.student_code, st2.student_code)
        legacy = Student.objects.get(pk=self.students[0].pk)  # eski usul: faqat full_name
        self.assertEqual((legacy.last_name, legacy.first_name), ("Oʻquvchi", "0"))

    def test_student_create_save_and_add_another(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get(reverse("oquvchilar_create")), "Saqlash va yana qoʻshish")
        r = self.client.post(reverse("oquvchilar_create"), {
            "last_name": "Aliyev", "first_name": "Vali", "middle_name": "", "school_class": self.cls.pk,
            "student_code": "", "is_active": "on", "save_add": "1"})
        self.assertRedirects(r, reverse("oquvchilar_create") + f"?school_class={self.cls.pk}")
        st = Student.objects.get(full_name="Aliyev Vali")
        self.assertEqual(st.school_class, self.cls)
        r = self.client.post(reverse("oquvchilar_create"), {
            "last_name": "Karimova", "first_name": "Gulnoza", "school_class": self.cls.pk, "is_active": "on"})
        self.assertRedirects(r, reverse("students") + f"?class={self.cls.pk}")

    # --- Pilot: mustaqil yo'qlama ---
    def test_blind_mode_hides_camera_until_ground_truth(self):
        s = self.start(pilot_blind=True)
        services.camera_mark_recognized(s.pk, self.students[0].pk, timezone.now(), 0.7)
        self.client.force_login(self.teacher)
        data = self.client.get(reverse("session_state", args=[s.pk])).json()
        self.assertTrue(data["hidden"])
        self.assertNotIn("status", data["records"][0])
        rec = s.records.first()
        resp = self.client.post(reverse("record_mark", args=[rec.pk]), json.dumps({"value": "present"}),
                                content_type="application/json")
        self.assertEqual(resp.status_code, 400)
        post = {f"gt_{r.pk}": ("present" if r.student_id != self.students[3].pk else "absent") for r in s.records.all()}
        self.client.post(reverse("session_ground_truth", args=[s.pk]), post)
        data = self.client.get(reverse("session_state", args=[s.pk])).json()
        self.assertFalse(data["hidden"])
        self.assertEqual(data["counts"]["camera"], 1)
        services.end_session(s, self.teacher)
        g = services.session_report(Session.objects.get(pk=s.pk)).ground_truth
        self.assertEqual((g["tp"], g["fp"], g["fn"]), (1, 0, 2))

    # --- Veb oqimi ---
    def test_teacher_web_flow(self):
        self.client.force_login(self.teacher)
        resp = self.client.post(reverse("session_start"), {"assignment": self.assignment.pk})
        s = Session.objects.get()
        self.assertRedirects(resp, reverse("session_detail", args=[s.pk]))
        self.assertEqual(self.client.get(reverse("session_detail", args=[s.pk])).status_code, 200)
        rec = s.records.first()
        resp = self.client.post(reverse("record_mark", args=[rec.pk]), json.dumps({"value": "present"}),
                                content_type="application/json")
        self.assertEqual(resp.json()["record"]["source"], "teacher")
        self.client.post(reverse("session_end", args=[s.pk]))
        self.client.post(reverse("session_confirm", args=[s.pk]))
        self.assertEqual(Session.objects.get().status, "confirmed")
        self.assertEqual(self.client.get(reverse("session_report", args=[s.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

    def test_admin_pages_render(self):
        self.client.force_login(self.admin)
        for name, args in [("students", []), ("photos", []), ("cameras", []),
                           ("audit_log", []), ("pilot", []), ("manage_sessions", []), ("dashboard", []),
                           ("manage_index", []), ("settings_edit", []), ("xonalar_list", []), ("sinflar_list", []),
                           ("foydalanuvchilar_list", []), ("biriktiruvlar_list", []), ("kameralar_create", []),
                           ("kameralar_edit", [self.camera.pk]), ("oquvchilar_edit", [self.students[0].pk]),
                           ("foydalanuvchilar_edit", [self.teacher.pk]), ("xonalar_delete", [self.room.pk])]:
            self.assertEqual(self.client.get(reverse(name, args=args)).status_code, 200, name)
        url = reverse("photos") + f"?student={self.students[0].pk}"
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertRedirects(self.client.get(reverse("student_detail", args=[self.students[0].pk])), url)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(reverse("students")).status_code, 403)
        self.assertEqual(self.client.get(reverse("manage_index")).status_code, 403)

    def test_sample_upload_in_memory(self):
        import cv2
        from django.core.files.uploadedfile import SimpleUploadedFile

        img = cv2.imencode(".png", np.full((200, 200, 3), 127, np.uint8))[1].tobytes()
        self.client.force_login(self.admin)
        url = reverse("photos") + f"?student={self.students[0].pk}"
        resp = self.client.post(url, {"action": "samples",
                                      "images": [SimpleUploadedFile("a.png", img, "image/png")]})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Rasmda yuz topilmadi")
        self.assertEqual(FaceTemplate.objects.filter(student=self.students[0]).count(), 1)

    @override_settings(CAMERA_PREVIEW_ENABLED=True, WORKER_PREVIEW_HOST="127.0.0.1", WORKER_PREVIEW_PORT=9)
    def test_teacher_sees_own_session_camera(self):
        s = self.start()
        url = reverse("session_camera", args=[s.pk])
        self.client.force_login(self.teacher)
        self.assertContains(self.client.get(reverse("session_detail", args=[s.pk])), url)
        r = self.client.get(url)  # worker ishlamayapti — tushunarli xato, lekin ruxsat bor
        self.assertEqual(r.status_code, 503)
        self.assertIn("worker", r.json()["error"])
        self.assertTrue(AuditLog.objects.filter(actor=self.teacher, action="camera_view").exists())
        self.client.force_login(self.other)  # boshqa o'qituvchi — ruxsat yo'q
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.teacher)
        services.end_session(s, self.teacher)
        r = self.client.get(url)
        self.assertEqual(r.status_code, 409)
        self.assertTrue(r.json()["stop"])
        self.assertNotContains(self.client.get(reverse("session_detail", args=[s.pk])), url)

    @override_settings(CAMERA_PREVIEW_ENABLED=True)
    def test_session_camera_hidden_in_blind_mode(self):
        s = self.start(pilot_blind=True)
        self.client.force_login(self.teacher)
        r = self.client.get(reverse("session_camera", args=[s.pk]))
        self.assertEqual(r.status_code, 403)
        self.assertIn("Mustaqil", r.json()["error"])

    # --- Administrator: sessiyalarni o'chirish ---
    def test_admin_deletes_sessions_with_confirmation(self):
        s1 = self.start()
        services.camera_mark_recognized(s1.pk, self.students[0].pk, timezone.now(), 0.7)
        services.end_session(s1, self.teacher)
        room2 = Room.objects.create(name="202")
        cam2 = Camera(room=room2, name="cam2")
        cam2.rtsp_url = "1"
        cam2.save()
        TeacherAssignment.objects.create(teacher=self.other, school_class=self.cls, room=room2)
        live = services.start_session(self.other, TeacherAssignment.objects.get(teacher=self.other))
        url = reverse("sessions_delete")
        self.client.force_login(self.admin)
        r = self.client.get(reverse("manage_sessions") + "?status=live")
        self.assertNotContains(r, f"Sessiya #{s1.pk} ni tanlash")  # faqat davom etayotganlar
        self.assertContains(r, f"Sessiya #{live.pk} ni tanlash", count=0)  # davom etayotganini tanlab bo'lmaydi
        self.assertContains(self.client.get(reverse("manage_sessions") + "?status=ended"), f"Sessiya #{s1.pk} ni tanlash")
        # 1-qadam: tasdiqlash sahifasi, hali hech narsa o'chmagan
        r = self.client.post(url, {"session_id": [s1.pk, live.pk]})
        self.assertContains(r, "davom etmoqda")
        self.assertEqual(Session.objects.count(), 2)
        # 2-qadam: o'chirish; davom etayotgani qoladi
        r = self.client.post(url, {"session_id": [s1.pk, live.pk], "confirm": "1",
                                   "next": reverse("session_detail", args=[s1.pk])})
        self.assertRedirects(r, reverse("manage_sessions"))
        self.assertEqual(list(Session.objects.values_list("pk", flat=True)), [live.pk])
        self.assertFalse(AttendanceRecord.objects.filter(session_id=s1.pk).exists())
        log = AuditLog.objects.get(action="session_delete")
        self.assertEqual((log.object_id, log.actor), (str(s1.pk), self.admin))
        self.assertIn("keldi 1/4", log.note)
        self.assertTrue(AuditLog.objects.filter(action="session_end").exists())  # eski audit saqlangan
        # tashqi manzilga yo'naltirib bo'lmaydi
        r = self.client.post(url, {"session_id": [live.pk], "confirm": "1", "next": "https://evil.example/"})
        self.assertRedirects(r, reverse("manage_sessions"))

    def test_session_delete_admin_only(self):
        s = self.start()
        services.end_session(s, self.teacher)
        self.client.force_login(self.teacher)
        r = self.client.post(reverse("sessions_delete"), {"session_id": [s.pk], "confirm": "1"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.get(reverse("manage_sessions")).status_code, 403)
        self.assertEqual(self.client.get(reverse("session_list")).status_code, 200)  # o'qituvchi — oddiy ro'yxat
        self.assertTrue(Session.objects.filter(pk=s.pk).exists())
        with self.assertRaises(PermissionDenied):
            services.delete_sessions(self.teacher, [s.pk])
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("session_list") + "?status=ended"),
                             reverse("manage_sessions") + "?status=ended")

    def test_template_thumbnail_admin_only(self):
        import cv2

        from vision.engine import face_thumbnail

        jpeg = face_thumbnail(np.full((400, 600, 3), 200, np.uint8), (500, 350, 80, 80))  # chetdagi yuz
        self.assertEqual(cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).shape, (160, 160, 3))
        t = FaceTemplate.objects.filter(student=self.students[0]).first()
        t.thumb_encrypted = crypto.encrypt_bytes(jpeg)
        t.save()
        self.assertNotEqual(bytes(t.thumb_encrypted), jpeg)  # bazada shifrlangan
        url = reverse("template_thumb", args=[t.pk])
        self.client.force_login(self.admin)
        r = self.client.get(url)
        self.assertEqual((r.status_code, r["Content-Type"], r.content), (200, "image/jpeg", jpeg))
        self.assertIn("no-store", r["Cache-Control"])
        page = self.client.get(reverse("photos") + f"?student={self.students[0].pk}")
        self.assertContains(page, url)
        other = FaceTemplate.objects.filter(student=self.students[1]).first()
        self.assertEqual(self.client.get(reverse("template_thumb", args=[other.pk])).status_code, 404)
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(url).status_code, 403)

    @override_settings(MAX_FACE_SAMPLE_BYTES=1000)
    def test_oversized_upload_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.admin)
        url = reverse("photos") + f"?student={self.students[0].pk}"
        resp = self.client.post(url, {"action": "samples", "images": [SimpleUploadedFile("a.jpg", b"x" * 5000)]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(FaceTemplate.objects.filter(student=self.students[0]).count(), 1)

    def test_role_syncs_staff_flags(self):
        self.assertTrue(self.admin.is_staff and self.admin.is_superuser)
        self.assertFalse(self.teacher.is_staff)
