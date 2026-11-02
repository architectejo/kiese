from django.contrib import admin
from .models import FinancialYear


@admin.register(FinancialYear)
class FinancialYearAdmin(admin.ModelAdmin):
    list_display  = ['year', 'is_current', 'is_closed', 'created_at']
    list_filter   = ['is_current', 'is_closed']
    readonly_fields = ['id', 'created_at', 'updated_at']
