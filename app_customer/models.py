from django.db import models


class Customer(models.Model):
    STATUS_CHOICES = [('Active', 'Active'), ('Inactive', 'Inactive')]

    customer_id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=150)

    email = models.EmailField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')

    class Meta:
        db_table = 'customer'
        ordering = ['name']

    def __str__(self):
        return self.name
