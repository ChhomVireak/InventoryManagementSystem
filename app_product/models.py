from django.core.validators import MinValueValidator
from django.db import models


class Category(models.Model):
    category_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = 'category'
        ordering = ['name']
        verbose_name_plural = 'categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    STATUS_CHOICES = [('Active', 'Active'), ('Discontinued', 'Discontinued')]

    product_id = models.AutoField(primary_key=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products')
    sku = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    unit_of_measure = models.CharField(max_length=20, default='pcs', help_text='e.g. pcs, kg, box')
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    selling_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    reorder_level = models.PositiveIntegerField(default=0, help_text='Alert when quantity on hand <= this level (0 = no alert)')
    is_batch_tracked = models.BooleanField(default=False)
    is_expiry_tracked = models.BooleanField(default=False)
    barcode = models.CharField(max_length=100, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')

    class Meta:
        db_table = 'product'
        ordering = ['name']
        constraints = [
            models.CheckConstraint(condition=models.Q(cost_price__gte=0), name='product_cost_price_gte_0'),
            models.CheckConstraint(condition=models.Q(selling_price__gte=0), name='product_selling_price_gte_0'),
        ]

    def __str__(self):
        return f'{self.sku} - {self.name}'

    @property
    def tracks_batches(self):
        """Expiry tracking needs a batch number as well."""
        return self.is_batch_tracked or self.is_expiry_tracked
