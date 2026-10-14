from django.core.exceptions import ValidationError
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

from ml.ahp import CRITERIA, ahp_weights, equal_matrix, validate_criteria_weights

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


class RankingSettings(models.Model):
    """The administrator's AHP comparisons for ranking doctors (a single row, pk=1).

    ``ahp_pairwise`` is the 5x5 comparison matrix over ml.ahp.CRITERIA; saving it
    computes ``ahp_weights`` (criterion -> weight) and the consistency ratio ``ahp_cr``.
    """
    ahp_pairwise = models.JSONField(default=equal_matrix)
    ahp_weights = models.JSONField(default=dict, blank=True)
    ahp_cr = models.FloatField(default=0.0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'ranking settings'
        verbose_name_plural = 'ranking settings'

    def clean(self):
        try:
            weights, cr = ahp_weights(self.ahp_pairwise)
            if len(weights) != len(CRITERIA):
                raise ValueError(f'the comparison matrix must be {len(CRITERIA)}x{len(CRITERIA)}')
            self.ahp_weights = validate_criteria_weights(
                {c: float(w) for c, w in zip(CRITERIA, weights)})
        except ValueError as exc:
            raise ValidationError({'ahp_pairwise': f'{str(exc)[:1].upper()}{str(exc)[1:]}.'})
        self.ahp_cr = round(cr, 4)

    def save(self, *args, **kwargs):
        self.pk = 1
        self.clean()
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'ahp_pairwise' in update_fields:
            # The weights and CR are computed from the matrix, so they are saved with it.
            kwargs['update_fields'] = {*update_fields, 'ahp_weights', 'ahp_cr'}
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> 'RankingSettings':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return f'Ranking settings (CR {self.ahp_cr:.3f})'
