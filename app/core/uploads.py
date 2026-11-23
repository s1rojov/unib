"""Yuklangan fayllar faqat xotirada saqlanadi.

Django standart holatda katta fayllarni vaqtinchalik diskka yozadi. Yuz namunalari
biometrik ma'lumot bo'lgani uchun diskka tushmasligi kerak: hajmi chegaradan oshgan
fayl rad etiladi.
"""
from django.conf import settings
from django.core.files.uploadhandler import MemoryFileUploadHandler, StopUpload


class MemoryOnlyUploadHandler(MemoryFileUploadHandler):
    def handle_raw_input(self, input_data, META, content_length, boundary, encoding=None):
        # Har doim xotirada ishlash (ota klass hajm katta bo'lsa diskka o'tishga ruxsat beradi)
        self.activated = True

    def receive_data_chunk(self, raw_data, start):
        if start + len(raw_data) > settings.MAX_FACE_SAMPLE_BYTES:
            raise StopUpload(connection_reset=False)
        return super().receive_data_chunk(raw_data, start)
