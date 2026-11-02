from django.db import models
from django.utils.translation import gettext_lazy as _


class FinancialYear(models.Model):
    """
    Reference year entity. Financial statements are computed on-the-fly
    by aggregating data from sales, production, commissions and treasury.
    """
    year       = models.PositiveSmallIntegerField(unique=True, verbose_name=_("Année"))
    is_current = models.BooleanField(default=False, verbose_name=_("Exercice courant"))
    is_closed  = models.BooleanField(default=False, verbose_name=_("Exercice clôturé"))
    notes      = models.TextField(blank=True, default='', verbose_name=_("Observations"))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Exercice Comptable")
        verbose_name_plural = _("Exercices Comptables")
        ordering = ['-year']

    def __str__(self):
        tag = " (Courant)" if self.is_current else ""
        return f"Exercice {self.year}{tag}"

    def save(self, *args, **kwargs):
        if self.is_current:
            FinancialYear.objects.exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)
