from functools import wraps

from django.core.exceptions import PermissionDenied


def perm_required(*codes):
    """RBAC guard: allow if the user holds ANY listed permission code (FR-22, NFR-04)."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated or not request.user.can(*codes):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def users_with_perm(*codes):
    """Active users whose role holds any of the permission codes."""
    from app_accounts.models import User
    return User.objects.filter(status='Active', role__permissions__permission_code__in=codes).distinct()
