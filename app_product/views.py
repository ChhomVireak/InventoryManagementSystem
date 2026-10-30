from django.db.models import Sum, Q
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404

from app_accounts.decorators import perm_required
from app_backend import crud
from app_product.forms import CategoryForm, ProductForm, UNITS
from app_product.models import Category, Product

BASE = '/product/'
CAT_BASE = '/product/category/'


def index(request):
    qs = Product.objects.select_related('category').annotate(on_hand=Sum('stocks__quantity_on_hand'))
    ctx = crud.list_context(
        request, qs, search_fields=['sku', 'name', 'barcode', 'category__name'],
        sort_fields={'sku': 'sku', 'name': 'name', 'category': 'category__name', 'cost': 'cost_price',
                     'price': 'selling_price', 'status': 'status', 'stock': 'on_hand'},
        default_sort='name', filters={'category': 'category_id', 'status': 'status'})
    ctx['categories'] = Category.objects.all()
    return render(request, 'pages/product/index.html', ctx)


def _extra():
    return {'units': UNITS}


@perm_required('product.manage')
def show_product(request):
    return crud.show_form(request, ProductForm, 'Product', BASE)


@perm_required('product.manage')
def create_product(request):
    return crud.save_form(request, ProductForm, 'Product', BASE)


@perm_required('product.manage')
def edit_product(request, id):
    return crud.show_form(request, ProductForm, 'Product', BASE, get_object_or_404(Product, pk=id))


@perm_required('product.manage')
def update_product(request, id):
    return crud.save_form(request, ProductForm, 'Product', BASE, get_object_or_404(Product, pk=id))


@perm_required('product.manage')
def delete_product(request, id):
    return crud.delete_object(request, Product, id, 'Product', BASE,
                              'It has stock history - set its status to Discontinued instead.')


# ----- categories (FR-02)
def category_index(request):
    from django.db.models import Count
    qs = Category.objects.annotate(product_count=Count('products'))
    ctx = crud.list_context(request, qs, search_fields=['name', 'description'],
                            sort_fields={'name': 'name', 'products': 'product_count'}, default_sort='name')
    return render(request, 'pages/product/category_index.html', ctx)


@perm_required('product.manage')
def show_category(request):
    return crud.show_form(request, CategoryForm, 'Category', CAT_BASE)


@perm_required('product.manage')
def create_category(request):
    return crud.save_form(request, CategoryForm, 'Category', CAT_BASE)


@perm_required('product.manage')
def edit_category(request, id):
    return crud.show_form(request, CategoryForm, 'Category', CAT_BASE, get_object_or_404(Category, pk=id))


@perm_required('product.manage')
def update_category(request, id):
    return crud.save_form(request, CategoryForm, 'Category', CAT_BASE, get_object_or_404(Category, pk=id))


@perm_required('product.manage')
def delete_category(request, id):
    return crud.delete_object(request, Category, id, 'Category', CAT_BASE, 'Move or delete its products first.')


# ----- JSON helpers for barcode scanning (FR-25) and the product picker (NFR-01)
def lookup(request):
    """Barcode / SKU lookup used by USB scanners and HTML5 camera scanning."""
    code = request.GET.get('barcode', '').strip()
    product = Product.objects.filter(Q(barcode=code) | Q(sku__iexact=code)).first() if code else None
    if product is None:
        return JsonResponse({'found': False}, status=404)
    return JsonResponse({'found': True, **_product_json(product)})


def search(request):
    """Select2 AJAX source: fast search over SKU / name / barcode (<= 30 rows)."""
    q = request.GET.get('q', '').strip()
    qs = Product.objects.all()
    if request.GET.get('active', '1') == '1':
        qs = qs.filter(status='Active')
    if q:
        qs = qs.filter(Q(sku__icontains=q) | Q(name__icontains=q) | Q(barcode__icontains=q))
    return JsonResponse({'results': [_product_json(p) for p in qs.order_by('name')[:30]]})


def _product_json(p):
    return {'id': p.pk, 'text': f'{p.sku} - {p.name}', 'sku': p.sku, 'name': p.name, 'uom': p.unit_of_measure,
            'cost': str(p.cost_price), 'price': str(p.selling_price),
            'batch': p.tracks_batches, 'expiry': p.is_expiry_tracked}
