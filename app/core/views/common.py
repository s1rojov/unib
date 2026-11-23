from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from ..models import Session
from ..services import can_view_session


def admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


def get_session_for(user, pk) -> Session:
    """Sessiyani olish va har so'rovda biriktiruvni server tomonda tekshirish."""
    session = get_object_or_404(Session.objects.select_related("school_class", "room", "camera", "teacher"), pk=pk)
    if not can_view_session(user, session):
        raise PermissionDenied
    return session
