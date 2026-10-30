from urllib.parse import quote

from django.conf import settings
from django.shortcuts import redirect


class LoginRequiredMiddleware:
    """FR-22: every page requires authentication except login, static and the API
    (the API authenticates with JWT and Django admin has its own login)."""

    EXEMPT_PREFIXES = ('/login/', '/static/', '/api/', '/admin/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated and not request.path.startswith(self.EXEMPT_PREFIXES):
            return redirect(f'{settings.LOGIN_URL}?next={quote(request.get_full_path())}')
        return self.get_response(request)
