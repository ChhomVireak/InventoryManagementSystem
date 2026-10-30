from urllib.parse import urlencode

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def startswith(value, prefix):
    return str(value).startswith(prefix)


@register.filter
def path_in(path, prefixes):
    """True when request.path starts with any comma separated prefix."""
    return any(path.startswith(p) for p in prefixes.split(',') if p)


@register.filter
def getattr_path(obj, path):
    """{{ row|getattr_path:'product.name' }} - safe dotted attribute lookup (callables are called)."""
    for part in path.split('.'):
        if obj is None:
            return ''
        obj = getattr(obj, part, '')
        if callable(obj):
            obj = obj()
    return obj


@register.filter
def has_perm_code(perms, code):
    return code in perms


@register.filter
def abs_value(value):
    try:
        return abs(value)
    except TypeError:
        return value


@register.simple_tag(takes_context=True)
def sort_link(context, field, label):
    """Sortable column header that keeps the current search/filter parameters (FR-24)."""
    request = context['request']
    current = context.get('sort', '')
    params = request.GET.copy()
    params.pop('page', None)
    descending = current == f'-{field}'
    ascending = current == field
    params['sort'] = field if descending or not ascending else f'-{field}'
    icon = ''
    if ascending:
        icon = ' <i class="fas fa-sort-up"></i>'
    elif descending:
        icon = ' <i class="fas fa-sort-down"></i>'
    return format_html('<a href="?{}" class="text-dark">{}{}</a>', urlencode(params, doseq=True), label,
                       mark_safe(icon))


STATUS_COLORS = {
    'Active': 'success', 'Inactive': 'secondary', 'Discontinued': 'dark',
    'Draft': 'secondary', 'Sent': 'info', 'Partial': 'warning', 'Received': 'success',
    'Cancelled': 'danger', 'Confirmed': 'info', 'Shipped': 'primary', 'Delivered': 'success',
    'Pending': 'warning', 'Approved': 'info', 'In Transit': 'primary', 'Completed': 'success',
    'Open': 'warning', 'Rejected': 'danger',
}


@register.filter
def status_badge(value):
    color = STATUS_COLORS.get(value, 'light')
    return format_html('<span class="badge badge-{}">{}</span>', color, value)
