from rest_framework import serializers
from .models import FinancialYear


class FinancialYearSerializer(serializers.ModelSerializer):
    class Meta:
        model  = FinancialYear
        fields = ['id', 'year', 'is_current', 'is_closed', 'notes', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate_year(self, value):
        # BUG-852 : bornes cohérentes avec `_validate_month_year` (year=0 -> 500 sur les états).
        if not 2000 <= value <= 2100:
            raise serializers.ValidationError("L'année doit être comprise entre 2000 et 2100.")
        return value
