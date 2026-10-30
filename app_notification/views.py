from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from app_backend import crud
from app_notification.models import Notification


def index(request):
    ctx = crud.list_context(
        request, Notification.objects.filter(user=request.user), search_fields=['message'],
        sort_fields={'date': 'created_at', 'type': 'type'}, default_sort='-created_at',
        filters={'type': 'type', 'read': 'is_read'})
    return render(request, 'pages/notification/index.html', ctx)


@require_POST
def mark_read(request, id):
    Notification.objects.filter(pk=id, user=request.user).update(is_read=True)
    return redirect(request.POST.get('next') or '/notification/')


@require_POST
def mark_all_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    messages.success(request, 'All notifications marked as read')
    return redirect('/notification/')
