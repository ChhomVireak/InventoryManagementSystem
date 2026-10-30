from rest_framework.permissions import SAFE_METHODS, BasePermission


class RBACPermission(BasePermission):
    """NFR-04: RBAC on every API endpoint. Reading needs a login; writing needs the
    permission named by the view's `write_permissions` (any one of them)."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated or not user.is_active:
            return False
        required = getattr(view, 'read_permissions', None) if request.method in SAFE_METHODS \
            else getattr(view, 'write_permissions', None)
        return True if not required else user.can(*required)
