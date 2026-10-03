"""Project-level views that do not belong to a feature app."""

from django.conf import settings
from django.db import connection
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """
    GET /api/health/

    Unauthenticated liveness and readiness probe. Reports the database engine
    actually in use so the SQLite fallback is visible rather than silent.

    Returns 200 when the database answers, 503 when it does not.
    """

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request):
        engine = connection.settings_dict["ENGINE"].rsplit(".", 1)[-1]
        database_ok, database_error = self._check_database()

        payload = {
            "status": "ok" if database_ok else "degraded",
            "service": "ecotrack-backend",
            "version": settings.ECOTRACK_VERSION,
            "environment": settings.ECOTRACK_ENVIRONMENT,
            "debug": settings.DEBUG,
            "time": timezone.now().isoformat(),
            "database": {
                "engine": engine,
                "configured_via": "DATABASE_URL" if settings.DATABASE_URL else "sqlite-fallback",
                "reachable": database_ok,
            },
        }
        if database_error:
            payload["database"]["error"] = database_error

        http_status = (
            status.HTTP_200_OK if database_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        )
        return Response(payload, status=http_status)

    @staticmethod
    def _check_database() -> tuple[bool, str | None]:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:  # pragma: no cover - exercised only when the DB is down
            return False, str(exc)
        return True, None
