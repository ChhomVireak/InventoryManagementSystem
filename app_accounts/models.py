from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils.functional import cached_property

from app_backend.utils import ImmutableModelMixin


class Permission(models.Model):
    permission_id = models.AutoField(primary_key=True)
    permission_code = models.CharField(max_length=60, unique=True, help_text='resource.action format')
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'permission'
        ordering = ['permission_code']

    def __str__(self):
        return self.permission_code


class Role(models.Model):
    role_id = models.AutoField(primary_key=True)
    role_name = models.CharField(max_length=50, unique=True)
    description = models.CharField(max_length=255, blank=True)
    permissions = models.ManyToManyField(Permission, db_table='role_permission', related_name='roles', blank=True)

    class Meta:
        db_table = 'role'
        ordering = ['role_name']

    def __str__(self):
        return self.role_name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, username, email, password=None, **extra):
        if not username or not email:
            raise ValueError('Username and email are required')
        if 'role' not in extra and 'role_id' not in extra:
            raise ValueError('A role is required')
        user = self.model(username=username, email=self.normalize_email(email), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email=None, password=None, **extra):
        from app_accounts.rbac import sync_rbac
        sync_rbac()
        extra['role'] = Role.objects.get(role_name='Admin')
        extra.setdefault('full_name', username)
        return self.create_user(username, email or f'{username}@example.com', password, **extra)


class User(AbstractBaseUser):
    STATUS_CHOICES = [('Active', 'Active'), ('Inactive', 'Inactive')]

    user_id = models.AutoField(primary_key=True)
    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name='users')
    username = models.CharField(max_length=50, unique=True)
    email = models.EmailField(max_length=100, unique=True)
    password = models.CharField(max_length=255, db_column='password_hash')   # Argon2 hash (NFR-03)
    full_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)

    objects = UserManager()
    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'full_name']

    class Meta:
        db_table = 'user'
        ordering = ['username']

    def __str__(self):
        return self.full_name or self.username

    # -- Django integration -------------------------------------------------
    @property
    def is_active(self):
        return self.status == 'Active'

    @property
    def is_staff(self):
        return self.is_active and self.role.role_name == 'Admin'

    def has_perm(self, perm, obj=None):
        return self.is_staff

    def has_module_perms(self, app_label):
        return self.is_staff

    # -- RBAC ----------------------------------------------------------------
    @cached_property
    def permission_codes(self):
        if not self.is_active:
            return frozenset()
        return frozenset(self.role.permissions.values_list('permission_code', flat=True))

    def can(self, *codes):
        """True if the user holds ANY of the given permission codes."""
        return any(c in self.permission_codes for c in codes)


class AuditLog(ImmutableModelMixin):

    log_id = models.AutoField(primary_key=True)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_logs')
    action = models.CharField(max_length=100)       # CREATE / UPDATE / DELETE / LOGIN / APPROVE / REJECT ...
    entity_name = models.CharField(max_length=50)   # table affected
    entity_id = models.IntegerField(null=True, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)   # IPv4 / IPv6
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_log'
        ordering = ['-created_at', '-log_id']

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} {self.action} {self.entity_name}#{self.entity_id}'
