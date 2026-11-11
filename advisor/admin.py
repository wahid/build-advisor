from django.contrib import admin

from .models import DailyUsage


@admin.register(DailyUsage)
class DailyUsageAdmin(admin.ModelAdmin):
    list_display = ("date", "questions")
