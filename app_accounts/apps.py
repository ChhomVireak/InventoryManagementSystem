from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AppAccountsConfig(AppConfig):
    name = 'app_accounts'

    def ready(self):
        from app_accounts.rbac import sync_rbac
        post_migrate.connect(sync_rbac, sender=self)
