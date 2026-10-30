"""Helpers for writing the immutable audit log (FR-23)."""
import json

from django.forms.models import model_to_dict


def client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    ip = forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')
    return ip or None


def snapshot(obj):
    """JSON snapshot of a model instance for old_value / new_value."""
    data = model_to_dict(obj)
    # never write password hashes to the log
    data.pop('password', None)
    return json.dumps(data, default=str, ensure_ascii=False)


def log(request, action, entity_name, entity_id=None, old=None, new=None, user=None):
    from app_accounts.models import AuditLog
    if user is None and request is not None and getattr(request, 'user', None) is not None \
            and request.user.is_authenticated:
        user = request.user
    return AuditLog.objects.create(
        user=user, action=action, entity_name=entity_name, entity_id=entity_id,
        old_value=old or '', new_value=new or '', ip_address=client_ip(request))


def log_obj(request, action, obj, old=None, new=None, user=None):
    return log(request, action, obj._meta.db_table, obj.pk, old=old,
               new=new if new is not None else snapshot(obj), user=user)
