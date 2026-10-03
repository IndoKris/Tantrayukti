"""Tests for the role-based permission classes.

The classes are exercised through throwaway views wired into a temporary URLconf,
so the behaviour tested is what DRF actually enforces on a request.
"""

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import path
from rest_framework.response import Response
from rest_framework.test import APITestCase
from rest_framework.views import APIView

from accounts.models import Role
from accounts.permissions import IsAdmin, IsManagerOrAbove, IsMember

User = get_user_model()


class _Probe(APIView):
    def get(self, request):
        return Response({"ok": True})


class MemberOnly(_Probe):
    permission_classes = [IsMember]


class ManagerOnly(_Probe):
    permission_classes = [IsManagerOrAbove]


class AdminOnly(_Probe):
    permission_classes = [IsAdmin]


urlpatterns = [
    path("probe/member/", MemberOnly.as_view()),
    path("probe/manager/", ManagerOnly.as_view()),
    path("probe/admin/", AdminOnly.as_view()),
]


@override_settings(ROOT_URLCONF=__name__)
class RolePermissionTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = User.objects.create_user(
            username="m", email="m@example.com", password="pw", role=Role.MEMBER
        )
        cls.manager = User.objects.create_user(
            username="g", email="g@example.com", password="pw", role=Role.MANAGER
        )
        cls.admin = User.objects.create_user(
            username="a", email="a@example.com", password="pw", role=Role.ADMIN
        )
        cls.superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="pw"
        )

    def assertAccess(self, user, url, allowed: bool):
        self.client.force_authenticate(user=user)
        response = self.client.get(url)
        expected = 200 if allowed else 403
        self.assertEqual(
            response.status_code,
            expected,
            f"{user.username} ({user.role}) -> {url}: expected {expected}, got {response.status_code}",
        )

    def test_anonymous_is_denied_everywhere(self):
        self.client.force_authenticate(user=None)
        for url in ("/probe/member/", "/probe/manager/", "/probe/admin/"):
            self.assertEqual(self.client.get(url).status_code, 401)

    def test_member_reaches_only_member_endpoints(self):
        self.assertAccess(self.member, "/probe/member/", allowed=True)
        self.assertAccess(self.member, "/probe/manager/", allowed=False)
        self.assertAccess(self.member, "/probe/admin/", allowed=False)

    def test_manager_reaches_member_and_manager_endpoints(self):
        self.assertAccess(self.manager, "/probe/member/", allowed=True)
        self.assertAccess(self.manager, "/probe/manager/", allowed=True)
        self.assertAccess(self.manager, "/probe/admin/", allowed=False)

    def test_admin_reaches_everything(self):
        for url in ("/probe/member/", "/probe/manager/", "/probe/admin/"):
            self.assertAccess(self.admin, url, allowed=True)

    def test_superuser_reaches_everything(self):
        for url in ("/probe/member/", "/probe/manager/", "/probe/admin/"):
            self.assertAccess(self.superuser, url, allowed=True)
