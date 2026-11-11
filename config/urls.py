from django.contrib import admin
from django.urls import path

from advisor.views import AskView, frontend
from wiki.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/ask/", AskView.as_view(), name="ask"),
    path("", frontend, name="frontend"),
]
