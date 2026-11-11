from django.apps import AppConfig
from django.conf import settings


class AdvisorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "advisor"
    verbose_name = "Build advisor"

    def ready(self) -> None:
        from .warmup import is_web_server, warm_up_in_background

        if settings.WARM_UP and is_web_server():
            warm_up_in_background()
