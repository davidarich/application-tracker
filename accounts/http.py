"""Request helpers for logged-in users."""

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest

from .models import User


def request_user(request: HttpRequest) -> User:
    """The logged-in user of a request. Use only behind @login_required."""
    user = request.user
    if not isinstance(user, User):
        raise TypeError("request_user() needs a logged-in user; use @login_required.")
    return user


def require_staff(request: HttpRequest) -> User:
    """The logged-in user, who must be staff (else 403). Use behind @login_required."""
    user = request_user(request)
    if not user.is_staff:
        raise PermissionDenied("Only staff can manage this.")
    return user
