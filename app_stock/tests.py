"""Business-rule tests for the stock engine and the order / transfer / count / return flows."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.utils import timezone

from app_accounts.models import AuditLog, Role, User
from app_accounts.rbac import sync_rbac
from app_customer.models import Customer
from app_notification.models import Notification
from app_product.models import Category, Product
from app_purchase.models import PurchaseOrder
from app_sales.models import SalesOrder
from app_stock import services
from app_stock.models import Stock, StockBatch, StockTransaction, StockTransactionLine
from app_stock.services import StockError
from app_supplier.models import Supplier
from app_warehouse.models import Warehouse

FAST = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def user(name, role):
    u = User(username=name, email=f'{name}@t.local', full_name=name, role=Role.objects.get(role_name=role))
    u.set_password('pw12345!')
    u.save()
    return u


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        sync_rbac()
        cls.admin = user('admin', 'Admin')
        cls.manager = user('manager', 'Inventory Manager')
        cls.staff = user('staff', 'Warehouse Staff')
        cls.sales = user('sales', 'Sales Staff')
        cls.cat = Category.objects.create(name='Cat')
        cls.w1 = Warehouse.objects.create(name='W1')
        cls.w2 = Warehouse.objects.create(name='W2')
        cls.plain = Product.objects.create(category=cls.cat, sku='P1', name='Plain', cost_price=5, selling_price=9,
                                           reorder_level=10)
        cls.batchy = Product.objects.create(category=cls.cat, sku='B1', name='Batchy', cost_price=2, selling_price=4,
                                            is_batch_tracked=True, is_expiry_tracked=True)

    def qty(self, product, wh):
        s = Stock.objects.filter(product=product, warehouse=wh).first()
        return s.quantity_on_hand if s else 0

    def receive(self, product, wh, qty, **kw):
        return services.record_in(warehouse=wh, user=self.admin,
                                  lines=[dict(product=product, quantity=qty, **kw)])


@FAST
class StockEngineTests(Base):
    def test_stock_in_and_out_update_quantity_and_ledger(self):
        self.receive(self.plain, self.w1, 30)
        self.assertEqual(self.qty(self.plain, self.w1), 30)
        services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.plain, 'quantity': 12}])
        self.assertEqual(self.qty(self.plain, self.w1), 18)
        lines = StockTransactionLine.objects.filter(product=self.plain).order_by('pk')
        self.assertEqual([l.quantity for l in lines], [30, -12])

    def test_insufficient_stock_blocks_dispatch_and_changes_nothing(self):
        self.receive(self.plain, self.w1, 5)
        before = StockTransaction.objects.count()
        with self.assertRaisesMessage(StockError, 'Insufficient stock'):
            services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.plain, 'quantity': 6}])
        self.assertEqual(self.qty(self.plain, self.w1), 5)
        self.assertEqual(StockTransaction.objects.count(), before)     # whole transaction rolled back

    def test_multi_line_out_is_atomic(self):
        self.receive(self.plain, self.w1, 10)
        with self.assertRaises(StockError):
            services.record_out(warehouse=self.w1, user=self.staff, lines=[
                {'product': self.plain, 'quantity': 4}, {'product': self.batchy, 'quantity': 1}])
        self.assertEqual(self.qty(self.plain, self.w1), 10)       # first line undone

    def test_zero_and_negative_quantity_rejected(self):
        for bad in (0, -3):
            with self.assertRaises(StockError):
                self.receive(self.plain, self.w1, bad)

    def test_batch_and_expiry_required_for_tracked_products(self):
        with self.assertRaisesMessage(StockError, 'batch number is required'):
            self.receive(self.batchy, self.w1, 5)
        with self.assertRaisesMessage(StockError, 'expiry date is required'):
            self.receive(self.batchy, self.w1, 5, batch_number='B1')
        with self.assertRaisesMessage(StockError, 'in the past'):
            self.receive(self.batchy, self.w1, 5, batch_number='B1',
                         expiry_date=timezone.localdate() - timedelta(days=1))

    def test_fefo_and_expired_batches_never_dispatched(self):
        today = timezone.localdate()
        self.receive(self.batchy, self.w1, 10, batch_number='LATE', expiry_date=today + timedelta(days=90))
        self.receive(self.batchy, self.w1, 10, batch_number='SOON', expiry_date=today + timedelta(days=10))
        services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.batchy, 'quantity': 12}])
        self.assertEqual(StockBatch.objects.get(batch_number='SOON').quantity_on_hand, 0)    # earliest expiry first
        self.assertEqual(StockBatch.objects.get(batch_number='LATE').quantity_on_hand, 8)
        # expire the remaining batch -> it can no longer be dispatched
        StockBatch.objects.filter(batch_number='LATE').update(expiry_date=today - timedelta(days=1))
        with self.assertRaisesMessage(StockError, 'expired'):
            services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.batchy, 'quantity': 1}])
        # ... but it can be written off with an adjustment
        services.record_adjustment(warehouse=self.w1, user=self.admin, lines=[{'product': self.batchy, 'quantity': -8}])
        self.assertEqual(self.qty(self.batchy, self.w1), 0)

    def test_batch_totals_match_stock(self):
        today = timezone.localdate()
        self.receive(self.batchy, self.w1, 7, batch_number='A', expiry_date=today + timedelta(days=30))
        self.receive(self.batchy, self.w1, 5, batch_number='B', expiry_date=today + timedelta(days=60))
        services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.batchy, 'quantity': 9}])
        total = sum(b.quantity_on_hand for b in StockBatch.objects.filter(product=self.batchy))
        self.assertEqual(total, self.qty(self.batchy, self.w1))
        self.assertEqual(total, 3)

    def test_ledger_is_immutable(self):
        txn = self.receive(self.plain, self.w1, 3)
        from app_backend.utils import ImmutableRecordError
        txn.notes = 'tamper'
        with self.assertRaises(ImmutableRecordError):
            txn.save()
        with self.assertRaises(ImmutableRecordError):
            txn.delete()
        with self.assertRaises(ImmutableRecordError):
            StockTransactionLine.objects.all().delete()

    def test_low_stock_notification_created_once(self):
        self.receive(self.plain, self.w1, 20)
        mgr = self.manager
        services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.plain, 'quantity': 12}])  # 8 <= 10
        self.assertEqual(Notification.objects.filter(user=mgr, type='LOW_STOCK').count(), 1)
        services.record_out(warehouse=self.w1, user=self.staff, lines=[{'product': self.plain, 'quantity': 1}])
        self.assertEqual(Notification.objects.filter(user=mgr, type='LOW_STOCK').count(), 1)    # deduplicated
        self.assertIn(self.plain, services.low_stock_products())


@FAST
class AdjustmentTests(Base):
    def test_reason_mandatory(self):
        with self.assertRaisesMessage(StockError, 'reason'):
            services.request_adjustment(user=self.staff, product=self.plain, warehouse=self.w1,
                                        quantity_change=1, reason='  ')

    @override_settings(ADJUSTMENT_APPROVAL_THRESHOLD=10)
    def test_threshold_and_approval(self):
        self.receive(self.plain, self.w1, 100)
        small = services.request_adjustment(user=self.staff, product=self.plain, warehouse=self.w1,
                                            quantity_change=-5, reason='damaged')
        self.assertEqual(small.status, 'Approved')                      # below threshold: applied at once
        self.assertEqual(self.qty(self.plain, self.w1), 95)
        big = services.request_adjustment(user=self.staff, product=self.plain, warehouse=self.w1,
                                          quantity_change=-40, reason='water damage')
        self.assertEqual(big.status, 'Pending')                         # above threshold: waits
        self.assertEqual(self.qty(self.plain, self.w1), 95)
        self.assertTrue(Notification.objects.filter(user=self.manager, type='APPROVAL').exists())
        services.apply_adjustment(big, approver=self.manager)
        self.assertEqual(self.qty(self.plain, self.w1), 55)
        with self.assertRaises(StockError):
            services.apply_adjustment(big, approver=self.manager)       # cannot approve twice

    @override_settings(ADJUSTMENT_APPROVAL_THRESHOLD=10)
    def test_reject(self):
        self.receive(self.plain, self.w1, 100)
        big = services.request_adjustment(user=self.staff, product=self.plain, warehouse=self.w1,
                                          quantity_change=-40, reason='lost')
        services.reject_adjustment(big, approver=self.manager)
        big.refresh_from_db()
        self.assertEqual(big.status, 'Rejected')
        self.assertEqual(self.qty(self.plain, self.w1), 100)

    def test_cannot_adjust_below_zero(self):
        self.receive(self.plain, self.w1, 3)
        with self.assertRaises(StockError):
            services.request_adjustment(user=self.manager, product=self.plain, warehouse=self.w1,
                                        quantity_change=-4, reason='oops')
        self.assertEqual(self.qty(self.plain, self.w1), 3)


@FAST
class TransferTests(Base):
    def test_full_transfer_flow_keeps_batch_and_expiry(self):
        exp = timezone.localdate() + timedelta(days=50)
        self.receive(self.plain, self.w1, 20)
        self.receive(self.batchy, self.w1, 10, batch_number='BX', expiry_date=exp)
        t = services.create_transfer(user=self.staff, from_warehouse=self.w1, to_warehouse=self.w2,
                                     transfer_date=timezone.localdate(),
                                     items=[(self.plain, 8), (self.batchy, 4)])
        self.assertEqual(t.status, 'Pending')
        with self.assertRaises(StockError):
            services.ship_transfer(t, user=self.staff)                   # not approved yet
        services.approve_transfer(t, approver=self.manager)
        services.ship_transfer(t, user=self.staff)
        self.assertEqual(self.qty(self.plain, self.w1), 12)
        self.assertEqual(self.qty(self.plain, self.w2), 0)               # in transit
        t.refresh_from_db()
        self.assertEqual(t.status, 'In Transit')
        services.receive_transfer(t, user=self.staff)
        self.assertEqual(self.qty(self.plain, self.w2), 8)
        b = StockBatch.objects.get(warehouse=self.w2, batch_number='BX')
        self.assertEqual((b.quantity_on_hand, b.expiry_date), (4, exp))
        # total stock conserved
        self.assertEqual(self.qty(self.plain, self.w1) + self.qty(self.plain, self.w2), 20)
        t.refresh_from_db()
        self.assertEqual(t.status, 'Completed')
        types = set(StockTransaction.objects.filter(reference_type='TRANSFER').values_list('transaction_type', flat=True))
        self.assertEqual(types, {'TRANSFER_OUT', 'TRANSFER_IN'})

    def test_same_warehouse_rejected(self):
        with self.assertRaisesMessage(StockError, 'different'):
            services.create_transfer(user=self.staff, from_warehouse=self.w1, to_warehouse=self.w1,
                                    transfer_date=timezone.localdate(), items=[(self.plain, 1)])

    def test_ship_fails_when_insufficient(self):
        self.receive(self.plain, self.w1, 2)
        t = services.create_transfer(user=self.staff, from_warehouse=self.w1, to_warehouse=self.w2,
                                     transfer_date=timezone.localdate(), items=[(self.plain, 5)])
        services.approve_transfer(t, approver=self.manager)
        with self.assertRaises(StockError):
            services.ship_transfer(t, user=self.staff)
        t.refresh_from_db()
        self.assertEqual(t.status, 'Approved')
        self.assertEqual(self.qty(self.plain, self.w1), 2)

    def test_reject_cancels(self):
        t = services.create_transfer(user=self.staff, from_warehouse=self.w1, to_warehouse=self.w2,
                                     transfer_date=timezone.localdate(), items=[(self.plain, 1)])
        services.reject_transfer(t, approver=self.manager)
        t.refresh_from_db()
        self.assertEqual(t.status, 'Cancelled')


@FAST
class CountTests(Base):
    def test_count_variance_and_approval(self):
        self.receive(self.plain, self.w1, 10)
        c = services.create_count(user=self.staff, warehouse=self.w1, count_date=timezone.localdate())
        with self.assertRaisesMessage(StockError, 'not been counted'):
            services.complete_count(c, user=self.staff)
        services.save_count_quantities(c, {self.plain.pk: 7})
        services.complete_count(c, user=self.staff)
        item = c.items.get()
        self.assertEqual((item.system_quantity, item.counted_quantity, item.variance), (10, 7, -3))
        self.assertEqual(self.qty(self.plain, self.w1), 10)             # nothing posted until approved
        services.approve_count(c, approver=self.manager)
        self.assertEqual(self.qty(self.plain, self.w1), 7)
        c.refresh_from_db()
        self.assertEqual(c.status, 'Approved')
        with self.assertRaises(StockError):
            services.save_count_quantities(c, {self.plain.pk: 1})       # no edits after completion


@FAST
class OrderFlowTests(Base):
    """Purchase -> receive -> sell -> dispatch -> return, through the real views (RBAC + forms)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.purchasing = user('buyer', 'Purchasing Officer')
        cls.supplier = Supplier.objects.create(name='Sup')
        cls.customer = Customer.objects.create(name='Cust')

    def login(self, name):
        self.client.logout()
        self.assertTrue(self.client.login(username=name, password='pw12345!'))

    def po_payload(self, **extra):
        data = {'supplier': self.supplier.pk, 'order_date': '2026-10-01', 'expected_date': '', 'discount_amount': '0',
                'notes': '', 'line_product': [self.plain.pk], 'line_quantity': ['10'], 'line_price': ['4.50']}
        data.update(extra)
        return data

    def test_purchase_flow(self):
        self.login('buyer')
        r = self.client.post('/purchase/create', self.po_payload(discount_amount='5'))
        po = PurchaseOrder.objects.get()
        self.assertRedirects(r, f'/purchase/{po.pk}/', fetch_redirect_response=False)
        self.assertEqual(po.status, 'Draft')
        self.assertEqual(po.total_amount, Decimal('40.00'))               # 10 x 4.50 - 5
        self.assertTrue(po.po_number.startswith('PO-'))
        # purchasing officer cannot approve (needs po.approve) and cannot receive a draft
        self.client.post(f'/purchase/{po.pk}/approve')
        po.refresh_from_db()
        self.assertEqual(po.status, 'Draft')
        self.login('manager')
        self.client.post(f'/purchase/{po.pk}/approve')
        po.refresh_from_db()
        self.assertEqual(po.status, 'Sent')
        # partial receipt
        item = po.items.get()
        self.login('staff')
        r = self.client.post(f'/purchase/{po.pk}/receive', {'warehouse': self.w1.pk, f'qty_{item.pk}': '4'})
        po.refresh_from_db()
        self.assertEqual(po.status, 'Partial')
        self.assertEqual(self.qty(self.plain, self.w1), 4)
        # cannot over-receive
        r = self.client.post(f'/purchase/{po.pk}/receive', {'warehouse': self.w1.pk, f'qty_{item.pk}': '7'})
        self.assertContains(r, 'only 6 still expected')
        self.assertEqual(self.qty(self.plain, self.w1), 4)
        self.client.post(f'/purchase/{po.pk}/receive', {'warehouse': self.w1.pk, f'qty_{item.pk}': '6'})
        po.refresh_from_db()
        self.assertEqual(po.status, 'Received')
        self.assertEqual(self.qty(self.plain, self.w1), 10)
        ledger = StockTransaction.objects.filter(reference_type='PO', reference_id=po.pk)
        self.assertEqual(ledger.count(), 2)
        # received orders cannot be cancelled
        self.login('manager')
        self.client.post(f'/purchase/{po.pk}/cancel')
        po.refresh_from_db()
        self.assertEqual(po.status, 'Received')
        self.assertTrue(AuditLog.objects.filter(action='RECEIVE', entity_name='purchase_order').exists())

    def test_po_validation(self):
        self.login('buyer')
        r = self.client.post('/purchase/create', self.po_payload(line_quantity=['0']))
        self.assertContains(r, 'quantity must be a whole number greater than zero')
        r = self.client.post('/purchase/create', self.po_payload(line_product=[''], line_quantity=[''], line_price=['']))
        self.assertContains(r, 'Add at least one product line')
        r = self.client.post('/purchase/create', self.po_payload(line_product=[self.plain.pk, self.plain.pk],
                                                                 line_quantity=['1', '1'], line_price=['1', '1']))
        self.assertContains(r, 'more than once')
        self.assertEqual(PurchaseOrder.objects.count(), 0)

    def so_payload(self, qty='5', price='9.00'):
        return {'customer': self.customer.pk, 'order_date': '2026-10-02', 'delivery_date': '', 'discount_amount': '0',
                'notes': '', 'line_product': [self.plain.pk], 'line_quantity': [qty], 'line_price': [price]}

    def test_sales_flow_with_tax_and_dispatch_rules(self):
        self.receive(self.plain, self.w1, 8)
        self.login('sales')
        self.client.post('/sales/create', self.so_payload(qty='10'))
        so = SalesOrder.objects.get()
        self.assertEqual(so.total_amount, Decimal('99.00'))               # 90 + 10% tax
        self.assertEqual(so.tax_amount, Decimal('9.00'))
        self.client.post(f'/sales/{so.pk}/confirm')
        so.refresh_from_db()
        self.assertEqual(so.status, 'Confirmed')
        item = so.items.get()
        # insufficient stock: 10 > 8 on hand -> blocked, nothing changes
        r = self.client.post(f'/sales/{so.pk}/dispatch', {'warehouse': self.w1.pk, f'qty_{item.pk}': '10'})
        self.assertContains(r, 'Insufficient stock')
        so.refresh_from_db(); item.refresh_from_db()
        self.assertEqual((so.status, item.quantity_shipped, self.qty(self.plain, self.w1)), ('Confirmed', 0, 8))
        # ship 8 now (partial), order stays Confirmed
        self.client.post(f'/sales/{so.pk}/dispatch', {'warehouse': self.w1.pk, f'qty_{item.pk}': '8'})
        so.refresh_from_db(); item.refresh_from_db()
        self.assertEqual((so.status, item.quantity_shipped, self.qty(self.plain, self.w1)), ('Confirmed', 8, 0))
        self.receive(self.plain, self.w1, 5)
        self.client.post(f'/sales/{so.pk}/dispatch', {'warehouse': self.w1.pk, f'qty_{item.pk}': '2'})
        so.refresh_from_db()
        self.assertEqual(so.status, 'Shipped')
        self.client.post(f'/sales/{so.pk}/deliver')
        so.refresh_from_db()
        self.assertEqual(so.status, 'Delivered')

    def test_sales_staff_cannot_create_purchase(self):
        self.login('sales')
        self.assertEqual(self.client.get('/purchase/formcreate').status_code, 403)
        self.login('buyer')
        self.assertEqual(self.client.get('/sales/formcreate').status_code, 403)

    def test_returns(self):
        # a delivered sales order, then a restockable + a damaged return
        self.receive(self.plain, self.w1, 10)
        self.login('sales')
        self.client.post('/sales/create', self.so_payload(qty='6'))
        so = SalesOrder.objects.get()
        self.client.post(f'/sales/{so.pk}/confirm')
        item = so.items.get()
        self.client.post(f'/sales/{so.pk}/dispatch', {'warehouse': self.w1.pk, f'qty_{item.pk}': '6'})
        self.assertEqual(self.qty(self.plain, self.w1), 4)
        # unknown order number is refused
        r = self.client.get('/returns/new?type=SALES_RETURN&order=SO-NOPE')
        self.assertContains(r, 'was not found')
        # cannot return more than shipped
        r = self.client.post('/returns/new', {'step': 'save', 'return_type': 'SALES_RETURN', 'order_number': so.so_number,
                                              'return_date': '2026-10-05', 'reason': 'bad', f'qty_{item.pk}': '7',
                                              f'cond_{item.pk}': 'Restockable'})
        self.assertContains(r, 'only 6 can still be returned')
        r = self.client.post('/returns/new', {'step': 'save', 'return_type': 'SALES_RETURN', 'order_number': so.so_number,
                                              'return_date': '2026-10-05', 'reason': 'wrong colour', f'qty_{item.pk}': '4',
                                              f'cond_{item.pk}': 'Restockable'})
        from app_returns.models import Return
        ret = Return.objects.get()
        self.assertEqual(ret.status, 'Pending')
        # sales staff cannot approve; manager can
        self.client.post(f'/returns/{ret.pk}/approve')
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'Pending')
        self.login('manager')
        self.client.post(f'/returns/{ret.pk}/approve')
        self.client.post(f'/returns/{ret.pk}/complete', {'warehouse': self.w1.pk})
        ret.refresh_from_db()
        self.assertEqual(ret.status, 'Completed')
        self.assertEqual(self.qty(self.plain, self.w1), 8)               # 4 restocked
        # remaining returnable = 6 - 4 = 2
        self.login('sales')
        r = self.client.post('/returns/new', {'step': 'save', 'return_type': 'SALES_RETURN', 'order_number': so.so_number,
                                              'return_date': '2026-10-06', 'reason': 'again', f'qty_{item.pk}': '3',
                                              f'cond_{item.pk}': 'Restockable'})
        self.assertContains(r, 'only 2 can still be returned')
        # damaged goods never re-enter stock
        self.client.post('/returns/new', {'step': 'save', 'return_type': 'SALES_RETURN', 'order_number': so.so_number,
                                          'return_date': '2026-10-06', 'reason': 'broken', f'qty_{item.pk}': '2',
                                          f'cond_{item.pk}': 'Damaged'})
        ret2 = Return.objects.exclude(pk=ret.pk).get()
        self.login('manager')
        self.client.post(f'/returns/{ret2.pk}/approve')
        self.client.post(f'/returns/{ret2.pk}/complete', {'warehouse': self.w1.pk})
        self.assertEqual(self.qty(self.plain, self.w1), 8)

    def test_purchase_return_removes_stock(self):
        self.login('buyer')
        self.client.post('/purchase/create', self.po_payload())
        po = PurchaseOrder.objects.get()
        self.login('manager')
        self.client.post(f'/purchase/{po.pk}/approve')
        item = po.items.get()
        self.client.post(f'/purchase/{po.pk}/receive', {'warehouse': self.w1.pk, f'qty_{item.pk}': '10'})
        self.login('buyer')
        self.client.post('/returns/new', {'step': 'save', 'return_type': 'PURCHASE_RETURN', 'order_number': po.po_number,
                                          'return_date': '2026-10-05', 'reason': 'faulty', f'qty_{item.pk}': '3'})
        from app_returns.models import Return
        ret = Return.objects.get()
        self.login('manager')
        self.client.post(f'/returns/{ret.pk}/approve')
        self.client.post(f'/returns/{ret.pk}/complete', {'warehouse': self.w1.pk})
        self.assertEqual(self.qty(self.plain, self.w1), 7)


@FAST
class ApiTests(Base):
    def token(self, username):
        r = self.client.post('/api/token/', {'username': username, 'password': 'pw12345!'},
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return {'HTTP_AUTHORIZATION': f'Bearer {r.json()["access"]}'}

    def test_requires_jwt(self):
        self.assertEqual(self.client.get('/api/products/').status_code, 401)

    def test_rbac_on_api(self):
        h = self.token('staff')
        self.assertEqual(self.client.get('/api/products/', **h).status_code, 200)
        r = self.client.post('/api/products/', {'sku': 'N', 'name': 'N', 'category': self.cat.pk, 'cost_price': '1',
                                                'selling_price': '2'}, content_type='application/json', **h)
        self.assertEqual(r.status_code, 403)
        h = self.token('manager')
        r = self.client.post('/api/products/', {'sku': 'N1', 'name': 'N', 'category': self.cat.pk, 'cost_price': '1',
                                                'selling_price': '2'}, content_type='application/json', **h)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertTrue(AuditLog.objects.filter(entity_name='product', action='CREATE').exists())

    def test_stock_in_out_over_api(self):
        h = self.token('staff')
        body = {'warehouse': self.w1.pk, 'product': self.plain.pk, 'quantity': 5}
        r = self.client.post('/api/stock-in/', body, content_type='application/json', **h)
        self.assertEqual(r.status_code, 201, r.content)
        r = self.client.post('/api/stock-out/', {**body, 'quantity': 9}, content_type='application/json', **h)
        self.assertEqual(r.status_code, 400)
        self.assertIn('Insufficient', r.json()['detail'])
        self.assertEqual(self.client.get('/api/stock/?barcode=P1', **h).json()['count'], 1)
        # sales staff may not record stock-in
        h = self.token('sales')
        self.assertEqual(self.client.post('/api/stock-in/', body, content_type='application/json', **h).status_code, 403)
