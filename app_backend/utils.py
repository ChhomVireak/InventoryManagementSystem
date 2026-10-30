"""Small shared helpers."""
from django.db import models


class ImmutableRecordError(Exception):
    """Raised when code tries to modify or delete an append-only record."""


class ImmutableQuerySet(models.QuerySet):
    """QuerySet that refuses bulk update/delete (used for ledger + audit log)."""

    def update(self, **kwargs):
        raise ImmutableRecordError('This table is append-only and cannot be updated.')

    def delete(self):
        raise ImmutableRecordError('This table is append-only and cannot be deleted from.')


class ImmutableModelMixin(models.Model):
    """Rows can be inserted but never changed or removed (NFR-06, O2)."""

    objects = ImmutableQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ImmutableRecordError(f'{self.__class__.__name__} records are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ImmutableRecordError(f'{self.__class__.__name__} records cannot be deleted.')


def next_number(model, field, prefix):
    """Generate a human-readable document number such as PO-20261027-0001."""
    from django.utils import timezone
    stamp = timezone.localdate().strftime('%Y%m%d')
    base = f'{prefix}-{stamp}-'
    last = (model.objects.filter(**{f'{field}__startswith': base})
            .order_by(f'-{field}').values_list(field, flat=True).first())
    seq = int(last.rsplit('-', 1)[1]) + 1 if last else 1
    return f'{base}{seq:04d}'
