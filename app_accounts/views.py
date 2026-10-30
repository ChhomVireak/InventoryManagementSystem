from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from app_accounts import audit
from app_accounts.decorators import perm_required
from app_accounts.forms import RoleForm, UserForm
from app_accounts.models import AuditLog, Role, User
from app_backend import crud


def login_view(request):
    if request.user.is_authenticated:
        return redirect('/admin_dashboard/')
    error = ''
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        user = authenticate(request, username=username, password=request.POST.get('password', ''))
        if user is not None:
            login(request, user)
            audit.log(request, 'LOGIN', 'user', user.pk, user=user)
            nxt = request.POST.get('next') or request.GET.get('next') or '/admin_dashboard/'
            if not url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
                nxt = '/admin_dashboard/'
            return redirect(nxt)
        audit.log(request, 'LOGIN_FAILED', 'user', None, new=username)
        error = 'Invalid username or password, or the account is inactive.'
    return render(request, 'pages/auth/login.html', {'error': error, 'next': request.GET.get('next', '')})


@require_POST
def logout_view(request):
    audit.log(request, 'LOGOUT', 'user', request.user.pk)
    logout(request)
    return redirect('/login/')


# ---------------------------------------------------------------- users (FR-21)
@perm_required('user.manage')
def user_index(request):
    ctx = crud.list_context(
        request, User.objects.select_related('role'),
        search_fields=['username', 'full_name', 'email'],
        sort_fields={'username': 'username', 'name': 'full_name', 'role': 'role__role_name', 'status': 'status'},
        default_sort='username', filters={'role': 'role_id', 'status': 'status'})
    ctx.update(roles=Role.objects.all())
    return render(request, 'pages/accounts/user_index.html', ctx)


@perm_required('user.manage')
def user_formcreate(request):
    return crud.show_form(request, UserForm, 'User', '/users/')


@perm_required('user.manage')
def user_create(request):
    return crud.save_form(request, UserForm, 'User', '/users/')


@perm_required('user.manage')
def user_edit(request, id):
    return crud.show_form(request, UserForm, 'User', '/users/', get_object_or_404(User, pk=id))


@perm_required('user.manage')
def user_update(request, id):
    return crud.save_form(request, UserForm, 'User', '/users/', get_object_or_404(User, pk=id))


@perm_required('user.manage')
@require_POST
def user_delete(request, id):
    if id == request.user.pk:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('/users/')
    return crud.delete_object(request, User, id, 'User', '/users/', 'Deactivate the user instead.')


# ---------------------------------------------------------------- roles
@perm_required('user.manage')
def role_index(request):
    return render(request, 'pages/accounts/role_index.html', {
        'roles': Role.objects.prefetch_related('permissions').all()})


@perm_required('user.manage')
def role_edit(request, id):
    return crud.show_form(request, RoleForm, 'Role', '/users/roles/', get_object_or_404(Role, pk=id))


@perm_required('user.manage')
def role_update(request, id):
    return crud.save_form(request, RoleForm, 'Role', '/users/roles/', get_object_or_404(Role, pk=id))


# ---------------------------------------------------------------- audit log
@perm_required('audit.view')
def audit_index(request):
    ctx = crud.list_context(
        request, AuditLog.objects.select_related('user'),
        search_fields=['entity_name', 'user__username', 'action', 'new_value'],
        sort_fields={'date': 'created_at', 'user': 'user__username', 'action': 'action', 'entity': 'entity_name'},
        default_sort='-created_at', filters={'action': 'action', 'entity': 'entity_name'}, per_page=15)
    ctx['actions'] = AuditLog.objects.order_by().values_list('action', flat=True).distinct()
    return render(request, 'pages/accounts/audit_index.html', ctx)
