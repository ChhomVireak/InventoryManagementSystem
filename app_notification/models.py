from django.db import models


class Notification(models.Model):
    TYPE_CHOICES = [('LOW_STOCK', 'Low stock'), ('EXPIRY', 'Expiry'), ('APPROVAL', 'Approval'),
                    ('ORDER_STATUS', 'Order status')]

    notification_id = models.AutoField(primary_key=True)
    user = models.ForeignKey('app_accounts.User', on_delete=models.CASCADE, related_name='notifications')
    type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    message = models.CharField(max_length=255)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_at', '-notification_id']

    def __str__(self):
        return f'{self.type}: {self.message}'
