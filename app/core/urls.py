from django.contrib.auth import views as auth_views
from django.urls import path

from .views import cameras, crud, manage, sessions

urlpatterns = [
    path("", sessions.dashboard, name="dashboard"),
    path("kirish/", auth_views.LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("chiqish/", auth_views.LogoutView.as_view(), name="logout"),
    # Sessiyalar (o'qituvchi)
    path("sessiyalar/", sessions.session_list, name="session_list"),
    path("sessiyalar/boshlash/", sessions.session_start, name="session_start"),
    path("sessiyalar/<int:pk>/", sessions.session_detail, name="session_detail"),
    path("sessiyalar/<int:pk>/holat/", sessions.session_state, name="session_state"),
    path("sessiyalar/<int:pk>/kamera.jpg", sessions.session_camera, name="session_camera"),
    path("sessiyalar/<int:pk>/korsatildi/", sessions.session_displayed, name="session_displayed"),
    path("sessiyalar/<int:pk>/yakunlash/", sessions.session_end, name="session_end"),
    path("sessiyalar/<int:pk>/tasdiqlash/", sessions.session_confirm, name="session_confirm"),
    path("sessiyalar/<int:pk>/yoqlama/", sessions.session_ground_truth, name="session_ground_truth"),
    path("sessiyalar/<int:pk>/hisobot/", sessions.session_report, name="session_report"),
    path("sessiyalar/<int:pk>/hisobot.csv", sessions.session_report_csv, name="session_report_csv"),
    path("sessiyalar/<int:pk>/kuzatuv/", sessions.session_observations, name="session_observations"),
    path("yozuvlar/<int:pk>/belgi/", sessions.record_mark, name="record_mark"),
    # Boshqaruv (administrator)
    path("boshqaruv/", crud.manage_index, name="manage_index"),
    path("boshqaruv/parametrlar/", crud.settings_edit, name="settings_edit"),
    path("boshqaruv/oquvchilar/", manage.students, name="students"),
    path("boshqaruv/oquvchilar/import/", crud.students_import, name="students_import"),
    path("boshqaruv/oquvchilar/<int:pk>/", manage.student_detail, name="student_detail"),
    path("boshqaruv/oquvchilar/<int:pk>/andozalar/ochirish/", manage.templates_delete, name="templates_delete"),
    path("boshqaruv/rasmlar/", manage.photos, name="photos"),
    path("boshqaruv/rasmlar/<int:pk>.jpg", manage.template_thumb, name="template_thumb"),
    path("boshqaruv/kameralar/", cameras.cameras, name="cameras"),
    path("boshqaruv/kameralar/<int:pk>/kadr.jpg", cameras.camera_snapshot, name="camera_snapshot"),
    path("boshqaruv/kameralar/<int:pk>/tekshirish/", cameras.camera_check, name="camera_check"),
    path("boshqaruv/audit/", manage.audit_log, name="audit_log"),
    path("boshqaruv/sessiyalar/", manage.manage_sessions, name="manage_sessions"),
    path("boshqaruv/sessiyalar/ochirish/", manage.sessions_delete, name="sessions_delete"),
    path("boshqaruv/pilot/", manage.pilot, name="pilot"),
    # Ma'lumotnomalar: xonalar, kameralar, sinflar, o'quvchilar, foydalanuvchilar, biriktiruvlar
    *crud.urlpatterns(),
]
