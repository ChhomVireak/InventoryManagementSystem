"""Parse the repeating line-item rows used by purchase orders, sales orders,
transfers and returns.  Each row posts: line_product, line_quantity, line_price."""
from decimal import Decimal, InvalidOperation

from app_product.models import Product


def parse_lines(post, *, with_price=True):
    ids = post.getlist('line_product')
    qtys = post.getlist('line_quantity')
    prices = post.getlist('line_price') if with_price else []
    products = {str(p.pk): p for p in Product.objects.filter(pk__in=[i for i in ids if i.isdigit()])}
    rows, errors, seen = [], [], set()
    for idx, pid in enumerate(ids):
        pid = pid.strip()
        if not pid:
            continue                      # blank row
        label = f'Line {idx + 1}'
        product = products.get(pid)
        if product is None:
            errors.append(f'{label}: product not found.')
            continue
        try:
            qty = int(qtys[idx])
        except (ValueError, IndexError):
            qty = 0
        if qty <= 0:
            errors.append(f'{label} ({product.sku}): quantity must be a whole number greater than zero.')
        price = None
        if with_price:
            try:
                price = Decimal(prices[idx])
                if price < 0:
                    raise InvalidOperation
            except (InvalidOperation, IndexError):
                errors.append(f'{label} ({product.sku}): unit price must be 0 or more.')
                price = Decimal('0')
        if product.pk in seen:
            errors.append(f'{label}: {product.sku} appears more than once - combine the quantities.')
        seen.add(product.pk)
        rows.append({'product': product, 'quantity': qty, 'price': price})
    if not rows and not errors:
        errors.append('Add at least one product line.')
    return rows, errors
