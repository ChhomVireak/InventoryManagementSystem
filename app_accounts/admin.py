from django.contrib import admin

from app_accounts.models import AuditLog, Permission, Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('role_name', 'description')
    filter_horizontal = ('permissions',)


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('permission_code', 'description')


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ('username', 'full_name', 'email', 'role', 'status')
    exclude = ('password', 'last_login')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: NFR-06 - audit entries cannot be modified by anyone."""
    list_display = ('created_at', 'user', 'action', 'entity_name', 'entity_id', 'ip_address')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
