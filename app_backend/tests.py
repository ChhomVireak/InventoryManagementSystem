"""End-to-end tests: every page renders for every role, RBAC blocks the right things,
and the audit log / ledger really are immutable."""
from django.test import TestCase, override_settings
from django.urls import reverse

from app_accounts.models import AuditLog, Role, User
from app_accounts.rbac import sync_rbac
from app_backend.utils import ImmutableRecordError

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def make_user(username, role):
    sync_rbac()
    u = User(username=username, email=f'{username}@t.local', full_name=username.title(),
             role=Role.objects.get(role_name=role))
    u.set_password('pw12345!')
    u.save()
    return u


@FAST_HASH
class AuthAndRbacTests(TestCase):
    def setUp(self):
        self.admin = make_user('admin', 'Admin')
        self.wh = make_user('wh', 'Warehouse Staff')
        self.acc = make_user('acc', 'Accountant')

    def login(self, name):
        self.client.login(username=name, password='pw12345!')

    def test_anonymous_redirected_to_login(self):
        for url in ['/admin_dashboard/', '/product/', '/stock/', '/purchase/']:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r['Location'].startswith('/login/'))

    def test_login_logout_and_audit(self):
        r = self.client.post('/login/', {'username': 'admin', 'password': 'pw12345!'})
        self.assertRedirects(r, '/admin_dashboard/', fetch_redirect_response=False)
        self.assertTrue(AuditLog.objects.filter(action='LOGIN', user=self.admin).exists())
        self.client.post('/logout/')
        self.assertEqual(self.client.get('/admin_dashboard/').status_code, 302)

    def test_bad_login_and_inactive_user(self):
        r = self.client.post('/login/', {'username': 'admin', 'password': 'wrong'})
        self.assertContains(r, 'Invalid username')
        self.admin.status = 'Inactive'
        self.admin.save()
        r = self.client.post('/login/', {'username': 'admin', 'password': 'pw12345!'})
        self.assertContains(r, 'Invalid username')

    def test_open_redirect_blocked(self):
        r = self.client.post('/login/', {'username': 'admin', 'password': 'pw12345!', 'next': 'https://evil.example'})
        self.assertRedirects(r, '/admin_dashboard/', fetch_redirect_response=False)

    def test_rbac_matrix(self):
        """Spot-check the permission matrix from the requirements (section 5.9)."""
        self.assertTrue(self.admin.can('user.manage'))
        self.assertFalse(self.wh.can('user.manage'))
        self.assertTrue(self.wh.can('stock.adjust.request'))
        self.assertFalse(self.wh.can('stock.adjust.approve'))
        self.assertTrue(self.acc.can('report.view'))
        self.assertFalse(self.acc.can('stock.in'))
        self.assertTrue(self.acc.can('audit.view'))

    def test_forbidden_actions(self):
        self.login('wh')
        self.assertEqual(self.client.get('/product/formcreate').status_code, 403)
        self.assertEqual(self.client.post('/product/create', {}).status_code, 403)
        self.assertEqual(self.client.get('/users/').status_code, 403)
        self.assertEqual(self.client.get('/report/').status_code, 403)
        self.assertEqual(self.client.get('/audit/').status_code, 403)
        self.assertEqual(self.client.get('/sales/formcreate').status_code, 403)

    def test_delete_requires_post(self):
        from app_product.models import Category
        c = Category.objects.create(name='X')
        self.login('admin')
        self.assertEqual(self.client.get(f'/product/category/delete/{c.pk}').status_code, 405)
        self.client.post(f'/product/category/delete/{c.pk}')
        self.assertFalse(Category.objects.filter(pk=c.pk).exists())

    def test_audit_log_is_immutable(self):
        log = AuditLog.objects.create(action='LOGIN', entity_name='user')
        log.action = 'X'
        with self.assertRaises(ImmutableRecordError):
            log.save()
        with self.assertRaises(ImmutableRecordError):
            log.delete()
        with self.assertRaises(ImmutableRecordError):
            AuditLog.objects.all().delete()
        with self.assertRaises(ImmutableRecordError):
            AuditLog.objects.all().update(action='Y')

    def test_password_not_stored_plain(self):
        self.assertNotEqual(self.admin.password, 'pw12345!')

    def test_user_crud_and_password_hash(self):
        self.login('admin')
        role = Role.objects.get(role_name='Sales Staff')
        r = self.client.post('/users/create', {'username': 'newbie', 'full_name': 'New Bie', 'email': 'n@t.local',
                                               'phone': '', 'role': role.pk, 'status': 'Active',
                                               'password': 'Str0ng-Passw0rd!'})
        self.assertRedirects(r, '/users/', fetch_redirect_response=False)
        u = User.objects.get(username='newbie')
        self.assertTrue(u.check_password('Str0ng-Passw0rd!'))
        # edit without password keeps the hash
        old = u.password
        self.client.post(f'/users/update/{u.pk}', {'username': 'newbie', 'full_name': 'Renamed', 'email': 'n@t.local',
                                                    'phone': '', 'role': role.pk, 'status': 'Active', 'password': ''})
        u.refresh_from_db()
        self.assertEqual(u.full_name, 'Renamed')
        self.assertEqual(u.password, old)
        # audit entries never contain the hash
        for log in AuditLog.objects.filter(entity_name='user', action__in=['CREATE', 'UPDATE']):
            self.assertNotIn(old, log.new_value + log.old_value)
        # new user needs a password
        r = self.client.post('/users/create', {'username': 'nopw', 'full_name': 'N', 'email': 'x@t.local',
                                               'role': role.pk, 'status': 'Active', 'password': ''})
        self.assertContains(r, 'Password is required')


@FAST_HASH
class SmokeCrawlTests(TestCase):
    """Every list / form page returns 200 for a role allowed to see it - catches template errors."""

    @classmethod
    def setUpTestData(cls):
        from django.core.management import call_command
        sync_rbac()
        call_command('seed_demo', verbosity=0)
        for u in User.objects.all():
            u.set_password('pw12345!')
            u.save()

    PAGES = {
        'admin': ['/admin_dashboard/', '/product/', '/product/formcreate', '/product/category/', '/product/category/formcreate',
                  '/warehouse/', '/warehouse/formcreate', '/supplier/', '/supplier/formcreate', '/customer/',
                  '/customer/formcreate', '/stock/', '/stock/?low=1', '/stock/in/', '/stock/out/',
                  '/stock/transactions/', '/stock/batches/', '/stock/batches/?state=expired', '/stock/adjustments/',
                  '/stock/adjustments/new', '/stock/transfers/', '/stock/transfers/new', '/stock/counts/',
                  '/stock/counts/new', '/purchase/', '/purchase/formcreate', '/sales/', '/sales/formcreate',
                  '/returns/', '/returns/new', '/notification/', '/report/', '/report/kpi/', '/users/',
                  '/users/formcreate', '/users/roles/', '/audit/', '/product/?keyword=lap&sort=-price',
                  '/stock/?keyword=milk&sort=qty', '/product/search/?q=lap', '/product/lookup/?barcode=8850001000011',
                  '/report/inventory/', '/report/low-stock/', '/report/valuation/', '/report/expiry/?days=60',
                  '/report/purchases/', '/report/sales/', '/report/returns/', '/report/movements/'],
        'warehouse': ['/admin_dashboard/', '/product/', '/stock/', '/stock/in/', '/stock/out/', '/stock/counts/',
                      '/stock/adjustments/new', '/stock/transfers/new', '/notification/', '/purchase/', '/sales/', '/returns/'],
        'accountant': ['/admin_dashboard/', '/report/', '/report/kpi/', '/report/valuation/', '/audit/', '/stock/'],
        'sales': ['/sales/formcreate', '/sales/', '/customer/formcreate', '/returns/new'],
        'purchasing': ['/purchase/formcreate', '/purchase/', '/supplier/formcreate'],
        'manager': ['/admin_dashboard/', '/product/formcreate', '/stock/adjustments/', '/report/kpi/', '/audit/'],
    }

    def test_pages_render(self):
        for username, urls in self.PAGES.items():
            self.client.logout()
            self.assertTrue(self.client.login(username=username, password='pw12345!'))
            for url in urls:
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, f'{username} GET {url} -> {r.status_code}')

    def test_csv_exports(self):
        self.client.login(username='accountant', password='pw12345!')
        for slug in ['inventory', 'low-stock', 'valuation', 'expiry', 'purchases', 'sales', 'returns', 'movements']:
            r = self.client.get(f'/report/{slug}/?export=csv')
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r['Content-Type'], 'text/csv')

    def test_barcode_lookup(self):
        self.client.login(username='warehouse', password='pw12345!')
        r = self.client.get('/product/lookup/?barcode=8850001000011')
        self.assertEqual(r.json()['sku'], 'LAP-001')
        self.assertEqual(self.client.get('/product/lookup/?barcode=nope').status_code, 404)
