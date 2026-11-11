from django.db import models


class DailyUsage(models.Model):
    """Questions answered per day (UTC), for the site-wide daily limit."""

    date = models.DateField(primary_key=True)
    questions = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-date"]
        verbose_name_plural = "daily usage"

    def __str__(self) -> str:
        return f"{self.date}: {self.questions} questions"
