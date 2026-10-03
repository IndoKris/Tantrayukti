from django.apps import AppConfig


class SatelliteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "satellite"
    verbose_name = "Satellite NO2 and community map"
