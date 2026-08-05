from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

class RecommendationHistory(models.Model):
    patient = models.ForeignKey('patients.Patient', on_delete=models.SET_NULL, null=True, blank=True, related_name='recommendation_history')
    symptoms = models.TextField()
    pain_level = models.IntegerField(help_text="Pain Level from 1 to 10", validators=[MinValueValidator(1), MaxValueValidator(10)])
    age = models.IntegerField(blank=True, null=True, validators=[MinValueValidator(1), MaxValueValidator(120)])
    medical_history = models.TextField(blank=True, null=True)
    recommended_doctor = models.ForeignKey('doctors.Doctor', on_delete=models.SET_NULL, null=True, blank=True, related_name='recommendations')
    recommended_department = models.CharField(max_length=50)
    score = models.FloatField(blank=True, null=True, help_text="Final decision score of the top doctor")
    confidence = models.IntegerField(blank=True, null=True, help_text="Department-match confidence (0-100)")
    reason = models.TextField(blank=True, null=True, help_text="Human-readable explanation of the recommendation")
    recommendation_date = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=['-recommendation_date']),
            models.Index(fields=['patient', '-recommendation_date']),
            models.Index(fields=['recommended_department', '-recommendation_date']),
        ]

    def __str__(self):
        return f"Rec for Age {self.age} - Dept: {self.recommended_department} ({self.recommendation_date.strftime('%Y-%m-%d')})"
