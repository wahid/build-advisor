from django.contrib import admin
from django.urls import path

from advisor.views import (
    AskView,
    FeedbackView,
    SharedChatView,
    ShareView,
    StatsView,
    frontend,
    shared_chat_page,
)
from wiki.views import health

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health, name="health"),
    path("api/ask/", AskView.as_view(), name="ask"),
    path("api/feedback/", FeedbackView.as_view(), name="feedback"),
    path("api/stats/", StatsView.as_view(), name="stats"),
    path("api/share/", ShareView.as_view(), name="share"),
    path("api/share/<slug:slug>/", SharedChatView.as_view(), name="shared-chat"),
    path("c/<slug:slug>/", shared_chat_page, name="shared-chat-page"),
    path("how-it-works/", frontend, name="how-it-works"),
    path("", frontend, name="frontend"),
]
