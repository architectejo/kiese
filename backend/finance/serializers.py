from rest_framework import serializers
from .models import FinancialYear


class FinancialYearSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FinancialYear
        fields = ['id', 'year', 'is_current', 'is_closed', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']
