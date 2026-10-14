from django.contrib import admin

from apps.recommendations.models import RankingSettings, RecommendationHistory


@admin.register(RecommendationHistory)
class RecommendationHistoryAdmin(admin.ModelAdmin):
    list_display = ('recommended_department', 'recommended_doctor', 'patient', 'confidence', 'recommendation_date')
    list_filter = ('recommended_department',)


@admin.register(RankingSettings)
class RankingSettingsAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'updated_at')
    readonly_fields = ('ahp_weights', 'ahp_cr', 'updated_at')

    def has_add_permission(self, request):
        return not RankingSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
