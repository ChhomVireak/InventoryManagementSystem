"""Reusable list / create / edit / update / delete helpers.

school_management repeats the same view code for every entity; here the shared
parts live in one place so every module (product, warehouse, supplier, ...)
keeps the same URL convention:

    /<entity>/                 list (search, filter, sort, pagination)   FR-24
    /<entity>/formcreate       empty form
    /<entity>/create           POST  -> save
    /<entity>/edit/<id>        filled form
    /<entity>/update/<id>      POST  -> save
    /<entity>/delete/<id>      POST  -> delete (confirmed with SweetAlert)
"""
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, ProtectedError, RestrictedError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from app_accounts import audit


def list_context(request, queryset, *, search_fields=(), sort_fields=None, default_sort='-pk',
                 filters=None, per_page=10):
    """Apply keyword search, exact-match filters and sorting, then paginate.

    sort_fields: {'public_name': 'orm__field'}  (whitelist - never trust request input)
    filters:     {'GET_param': 'orm__lookup'}
    """
    keyword = request.GET.get('keyword', '').strip()
    if keyword and search_fields:
        q = Q()
        for field in search_fields:
            q |= Q(**{f'{field}__icontains': keyword})
        queryset = queryset.filter(q)

    active_filters = {}
    for param, lookup in (filters or {}).items():
        value = request.GET.get(param, '').strip()
        if value:
            queryset = queryset.filter(**{lookup: value})
            active_filters[param] = value

    sort = request.GET.get('sort', '') or default_sort
    sort_fields = sort_fields or {}
    key = sort.lstrip('-')
    if key in sort_fields:
        queryset = queryset.order_by(('-' if sort.startswith('-') else '') + sort_fields[key], '-pk')
    else:
        queryset = queryset.order_by(default_sort)
        sort = default_sort

    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return {
        'page': page, 'keyword': keyword, 'sort': sort, 'filters': active_filters,
        'qs': params.urlencode(),
    }


def _form_response(request, form, title, action, back_url, extra=None):
    ctx = {'form': form, 'title': title, 'action': action, 'back_url': back_url}
    ctx.update(extra or {})
    return render(request, 'pages/crud/form.html', ctx)


def show_form(request, form_class, title, base_url, instance=None):
    """GET: render the (empty or pre-filled) form."""
    form = form_class(instance=instance)
    if instance is None:
        return _form_response(request, form, f'New {title}', f'{base_url}create', base_url)
    return _form_response(request, form, f'Edit {title}', f'{base_url}update/{instance.pk}', base_url)


def save_form(request, form_class, title, base_url, instance=None):
    """POST: validate (clear messages - NFR-10), save, write the audit log."""
    if request.method != 'POST':
        return redirect(base_url)
    old = audit.snapshot(instance) if instance is not None else None
    form = form_class(request.POST, instance=instance)
    if form.is_valid():
        obj = form.save()
        if instance is None:
            audit.log_obj(request, 'CREATE', obj)
            messages.success(request, f'{title} created successfully')
        else:
            audit.log_obj(request, 'UPDATE', obj, old=old)
            messages.success(request, f'{title} updated successfully')
        return redirect(base_url)
    messages.error(request, 'Please correct the highlighted errors.')
    if instance is None:
        return _form_response(request, form, f'New {title}', f'{base_url}create', base_url)
    return _form_response(request, form, f'Edit {title}', f'{base_url}update/{instance.pk}', base_url)


@require_POST
def delete_object(request, model, pk, title, base_url, hint=''):
    obj = get_object_or_404(model, pk=pk)
    old = audit.snapshot(obj)
    try:
        obj.delete()
    except (ProtectedError, RestrictedError, IntegrityError):
        messages.error(request, f'{title} is in use and cannot be deleted. {hint}'.strip())
    else:
        audit.log(request, 'DELETE', model._meta.db_table, pk, old=old)
        messages.success(request, f'{title} deleted successfully')
    return redirect(base_url)
