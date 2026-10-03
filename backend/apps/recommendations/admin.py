from django.contrib import admin

from apps.recommendations.models import RecommendationHistory


@admin.register(RecommendationHistory)
class RecommendationHistoryAdmin(admin.ModelAdmin):
    list_display = ('recommended_department', 'recommended_doctor', 'patient', 'confidence', 'recommendation_date')
    list_filter = ('recommended_department',)
