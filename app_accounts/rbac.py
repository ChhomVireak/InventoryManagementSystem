"""Role -> permission matrix from section 5.9 of the IMS analysis (FR-21, FR-22).

Permission codes use the `resource.action` format (PERMISSION.permission_code).
"Request" vs "approve" reproduces the "(request)" / "(approve)" cells of the matrix.
"""

PERMISSIONS = {
    'user.manage': 'Manage users and roles',
    'product.manage': 'Manage products and categories',
    'warehouse.manage': 'Manage warehouses',
    'partner.manage': 'Manage suppliers and customers',
    'stock.in': 'Record stock-in',
    'stock.out': 'Record stock-out',
    'stock.adjust.request': 'Request stock adjustment',
    'stock.adjust.approve': 'Approve stock adjustment (also approves returns and stock counts)',
    'stock.transfer.request': 'Request / ship / receive stock transfer',
    'stock.transfer.approve': 'Approve stock transfer',
    'stock.count': 'Stock counting',
    'po.create': 'Create purchase orders',
    'po.approve': 'Approve purchase orders',
    'po.receive': 'Receive goods',
    'so.create': 'Create sales orders',
    'so.dispatch': 'Dispatch goods',
    'return.process': 'Process returns',
    'report.view': 'View reports',
    'audit.view': 'View audit log',
}

ALL = list(PERMISSIONS)

ROLES = {
    'Admin': ('Manage users, roles, permissions; full access', ALL),
    'Inventory Manager': (
        'Approve adjustments and transfers; monitor stock; view reports',
        ['product.manage', 'warehouse.manage', 'partner.manage', 'stock.in', 'stock.out',
         'stock.adjust.approve', 'stock.transfer.approve', 'stock.count', 'po.create', 'po.approve',
         'po.receive', 'so.dispatch', 'return.process', 'report.view', 'audit.view']),
    'Warehouse Staff': (
        'Record stock-in/out, transfers, counts; scan barcodes',
        ['stock.in', 'stock.out', 'stock.adjust.request', 'stock.transfer.request', 'stock.count',
         'po.receive', 'so.dispatch', 'return.process']),
    'Purchasing Officer': (
        'Create and manage purchase orders; receive goods',
        ['partner.manage', 'stock.in', 'po.create', 'po.receive', 'return.process', 'report.view']),
    'Sales Staff': (
        'Create sales orders; dispatch goods; process returns',
        ['partner.manage', 'stock.out', 'so.create', 'so.dispatch', 'return.process', 'report.view']),
    'Accountant': ('View valuation and inventory reports', ['report.view', 'audit.view']),
}


def sync_rbac(**kwargs):
    """Idempotent: make sure every permission/role exists. Permissions of an
    existing role are left alone so an Admin can customise them later; the
    Admin role is always kept at full access."""
    from app_accounts.models import Permission, Role

    perms = {}
    for code, description in PERMISSIONS.items():
        perm, _ = Permission.objects.get_or_create(permission_code=code, defaults={'description': description})
        perms[code] = perm
    for name, (description, codes) in ROLES.items():
        role, created = Role.objects.get_or_create(role_name=name, defaults={'description': description})
        if created or name == 'Admin':
            role.permissions.set([perms[c] for c in codes])
