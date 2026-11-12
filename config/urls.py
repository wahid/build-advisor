from django.contrib import admin
from django.urls import path

from advisor.views import AskView, FeedbackView, StatsView, frontend
from wiki.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/ask/", AskView.as_view(), name="ask"),
    path("api/feedback/", FeedbackView.as_view(), name="feedback"),
    path("api/stats/", StatsView.as_view(), name="stats"),
    path("how-it-works/", frontend, name="how-it-works"),
    path("", frontend, name="frontend"),
]
