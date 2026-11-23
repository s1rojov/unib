from django.http import HttpResponse
from django.urls import include, path

urlpatterns = [
    path("healthz", lambda r: HttpResponse("ok"), name="healthz"),
    path("", include("core.urls")),
]
