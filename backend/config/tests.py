"""Tests for the project-level configuration and the health endpoint."""

from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class HealthEndpointTests(TestCase):
    def test_health_returns_200(self):
        response = self.client.get(reverse("health"))
        self.assertEqual(response.status_code, 200)

    def test_health_requires_no_authentication(self):
        """The probe must answer for anonymous callers despite the global IsAuthenticated default."""
        response = self.client.get("/api/health/")
        self.assertEqual(response.status_code, 200)

    def test_health_reports_status_ok_and_service_name(self):
        payload = self.client.get(reverse("health")).json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["service"], "ecotrack-backend")

    def test_health_reports_expected_keys(self):
        payload = self.client.get(reverse("health")).json()
        for key in ("status", "service", "version", "environment", "debug", "time", "database"):
            self.assertIn(key, payload)

    def test_health_reports_reachable_database_and_engine(self):
        database = self.client.get(reverse("health")).json()["database"]
        self.assertTrue(database["reachable"])
        self.assertIn("engine", database)
        self.assertIn(database["configured_via"], {"DATABASE_URL", "sqlite-fallback"})


class SettingsTests(SimpleTestCase):
    def test_cors_and_drf_are_installed(self):
        from django.conf import settings

        self.assertIn("corsheaders", settings.INSTALLED_APPS)
        self.assertIn("rest_framework", settings.INSTALLED_APPS)

    def test_cors_middleware_precedes_common_middleware(self):
        from django.conf import settings

        middleware = settings.MIDDLEWARE
        self.assertLess(
            middleware.index("corsheaders.middleware.CorsMiddleware"),
            middleware.index("django.middleware.common.CommonMiddleware"),
        )

    def test_database_falls_back_to_sqlite_without_database_url(self):
        """Documented fallback: the project must run with no DATABASE_URL set."""
        from django.conf import settings

        if not settings.DATABASE_URL:
            self.assertEqual(
                settings.DATABASES["default"]["ENGINE"], "django.db.backends.sqlite3"
            )
