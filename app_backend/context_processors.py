def ims(request):
    """Expose RBAC permissions and unread notifications to every template."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    from app_notification.models import Notification
    unread = Notification.objects.filter(user=user, is_read=False)
    return {
        'user_perms': user.permission_codes,
        'unread_count': unread.count(),
        'recent_notifications': list(unread.order_by('-created_at')[:5]),
    }
