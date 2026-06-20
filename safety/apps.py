from django.apps import AppConfig


class SafetyConfig(AppConfig):
    name = 'safety'

    def ready(self):
        import safety.signals  # noqa: F401
