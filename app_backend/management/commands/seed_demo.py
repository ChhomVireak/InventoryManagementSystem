"""python manage.py seed_demo  - demo users, master data and opening stock (development only)."""
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils import timezone

from app_accounts.models import Role, User
from app_accounts.rbac import sync_rbac
from app_customer.models import Customer
from app_product.models import Category, Product
from app_stock import services
from app_supplier.models import Supplier
from app_warehouse.models import Warehouse

PASSWORD = 'Ims@12345'

USERS = [
    ('admin', 'Admin', 'System Administrator'),
    ('manager', 'Inventory Manager', 'Sokha Inventory Manager'),
    ('warehouse', 'Warehouse Staff', 'Dara Warehouse'),
    ('purchasing', 'Purchasing Officer', 'Vanna Purchasing'),
    ('sales', 'Sales Staff', 'Srey Sales'),
    ('accountant', 'Accountant', 'Bopha Accountant'),
]

PRODUCTS = [
    # sku, name, category, uom, cost, price, reorder, batch, expiry, barcode
    ('LAP-001', 'Business Laptop 14"', 'Electronics', 'pcs', '520.00', '699.00', 5, False, False, '8850001000011'),
    ('MOU-001', 'Wireless Mouse', 'Electronics', 'pcs', '6.50', '12.00', 20, False, False, '8850001000028'),
    ('KEY-001', 'Mechanical Keyboard', 'Electronics', 'pcs', '22.00', '39.00', 10, False, False, '8850001000035'),
    ('PAP-A4', 'A4 Paper (box of 5 reams)', 'Office Supplies', 'box', '11.00', '16.50', 15, False, False, '8850001000042'),
    ('PEN-BLU', 'Ballpoint Pen Blue', 'Office Supplies', 'pcs', '0.15', '0.40', 200, False, False, '8850001000059'),
    ('MLK-001', 'UHT Milk 1L', 'Food & Beverage', 'pcs', '0.90', '1.40', 50, True, True, '8850001000066'),
    ('WAT-500', 'Mineral Water 500ml', 'Food & Beverage', 'pcs', '0.20', '0.45', 100, True, True, '8850001000073'),
    ('SAN-001', 'Hand Sanitizer 250ml', 'Health', 'bottle', '1.80', '3.20', 30, True, False, '8850001000080'),
]


class Command(BaseCommand):
    help = 'Create demo users, master data and opening stock.'

    def handle(self, *args, **options):
        sync_rbac()
        for username, role, name in USERS:
            user, created = User.objects.get_or_create(
                username=username, defaults={'role': Role.objects.get(role_name=role), 'full_name': name,
                                             'email': f'{username}@ims.local'})
            if created:
                user.set_password(PASSWORD)
                user.save()
        admin = User.objects.get(username='admin')

        main, _ = Warehouse.objects.get_or_create(name='Main Warehouse', defaults={
            'location': 'Phnom Penh', 'address': 'National Road 4, Phnom Penh'})
        branch, _ = Warehouse.objects.get_or_create(name='Siem Reap Branch', defaults={
            'location': 'Siem Reap', 'address': 'National Road 6, Siem Reap'})

        for name in ['Electronics', 'Office Supplies', 'Food & Beverage', 'Health']:
            Category.objects.get_or_create(name=name)
        for sku, name, cat, uom, cost, price, reorder, batch, expiry, barcode in PRODUCTS:
            Product.objects.get_or_create(sku=sku, defaults=dict(
                name=name, category=Category.objects.get(name=cat), unit_of_measure=uom,
                cost_price=Decimal(cost), selling_price=Decimal(price), reorder_level=reorder,
                is_batch_tracked=batch, is_expiry_tracked=expiry, barcode=barcode))

        Supplier.objects.get_or_create(name='Angkor Tech Supply', defaults={
            'contact_person': 'Mr. Chea', 'email': 'sales@angkortech.example', 'phone': '012345678'})
        Supplier.objects.get_or_create(name='Mekong Foods Co.', defaults={
            'contact_person': 'Ms. Lina', 'email': 'orders@mekongfoods.example', 'phone': '098765432'})
        Customer.objects.get_or_create(name='Sovann Trading', defaults={'phone': '011223344'})
        Customer.objects.get_or_create(name='Bayon Office Mart', defaults={'phone': '077889900'})

        from app_stock.models import Stock
        if not Stock.objects.exists():
            today = timezone.localdate()
            p = {x.sku: x for x in Product.objects.all()}
            services.record_in(warehouse=main, user=admin, notes='Opening stock', lines=[
                {'product': p['LAP-001'], 'quantity': 12}, {'product': p['MOU-001'], 'quantity': 60},
                {'product': p['KEY-001'], 'quantity': 8}, {'product': p['PAP-A4'], 'quantity': 40},
                {'product': p['PEN-BLU'], 'quantity': 150},
                {'product': p['MLK-001'], 'quantity': 120, 'batch_number': 'MLK-2610A',
                 'expiry_date': today + timedelta(days=20)},
                {'product': p['MLK-001'], 'quantity': 200, 'batch_number': 'MLK-2701B',
                 'expiry_date': today + timedelta(days=120)},
                {'product': p['WAT-500'], 'quantity': 500, 'batch_number': 'WAT-2612',
                 'expiry_date': today + timedelta(days=300)},
                {'product': p['SAN-001'], 'quantity': 25, 'batch_number': 'SAN-01'}])
            services.record_in(warehouse=branch, user=admin, notes='Opening stock', lines=[
                {'product': p['MOU-001'], 'quantity': 15}, {'product': p['PAP-A4'], 'quantity': 10}])
        self.stdout.write(self.style.SUCCESS(
            f'Demo data ready. Log in with admin / manager / warehouse / purchasing / sales / accountant '
            f'and password {PASSWORD}'))
