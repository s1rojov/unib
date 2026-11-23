"""Sinov uchun namunaviy ma'lumotlar: xona, kamera, sinf, o'quvchilar, o'qituvchi."""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import Camera, Room, SchoolClass, Student, TeacherAssignment, User


class Command(BaseCommand):
    help = "Namunaviy maʼlumotlarni yaratadi (faqat sinov uchun)"

    def add_arguments(self, parser):
        parser.add_argument("--rtsp", default="0", help="RTSP manzil yoki kompyuter kamerasi raqami (0)")
        parser.add_argument("--teacher-password", default="oqituvchi123")
        parser.add_argument("--students", type=int, default=10)

    @transaction.atomic
    def handle(self, *args, **o):
        room, _ = Room.objects.get_or_create(name="101-xona")
        cam = Camera.objects.filter(room=room).first() or Camera(room=room, name="Sinf kamerasi")
        cam.rtsp_url = o["rtsp"]
        cam.save()
        cls, _ = SchoolClass.objects.get_or_create(name="7-A", academic_year="2026-2027")
        for i in range(1, o["students"] + 1):
            Student.objects.get_or_create(
                student_code=f"7A-{i:03d}", defaults={"full_name": f"Oʻquvchi {i:02d}", "school_class": cls}
            )
        teacher = User.objects.filter(username="oqituvchi").first()
        if teacher is None:
            teacher = User(username="oqituvchi", first_name="Namuna", last_name="Oʻqituvchi", role=User.Role.TEACHER)
            teacher.set_password(o["teacher_password"])
            teacher.save()
        TeacherAssignment.objects.get_or_create(teacher=teacher, school_class=cls, room=room)
        self.stdout.write(self.style.SUCCESS(
            f"Tayyor: xona={room}, sinf={cls}, oʻquvchilar={cls.students.count()}, oʻqituvchi login=oqituvchi"
        ))
