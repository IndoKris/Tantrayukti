"""Tests for JWT login, refresh and the current-user endpoint."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from accounts.models import Role

User = get_user_model()


class LoginTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="manager1",
            email="manager1@example.com",
            password="correct-horse-battery",
            role=Role.MANAGER,
        )

    def test_login_returns_access_refresh_and_user(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "manager1", "password": "correct-horse-battery"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("access", body)
        self.assertIn("refresh", body)
        self.assertEqual(body["user"]["username"], "manager1")
        self.assertEqual(body["user"]["role"], Role.MANAGER)
        self.assertEqual(body["user"]["role_display"], "Manager")

    def test_login_response_never_includes_the_password(self):
        body = self.client.post(
            reverse("accounts:login"),
            {"username": "manager1", "password": "correct-horse-battery"},
        ).json()
        self.assertNotIn("password", body["user"])

    def test_access_token_carries_the_role_claim(self):
        from rest_framework_simplejwt.tokens import AccessToken

        access = self.client.post(
            reverse("accounts:login"),
            {"username": "manager1", "password": "correct-horse-battery"},
        ).json()["access"]
        self.assertEqual(AccessToken(access)["role"], Role.MANAGER)

    def test_login_with_wrong_password_is_rejected(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "manager1", "password": "wrong"}
        )
        self.assertEqual(response.status_code, 401)

    def test_login_with_unknown_user_is_rejected(self):
        response = self.client.post(
            reverse("accounts:login"), {"username": "nobody", "password": "whatever"}
        )
        self.assertEqual(response.status_code, 401)

    def test_inactive_user_cannot_log_in(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "manager1", "password": "correct-horse-battery"},
        )
        self.assertEqual(response.status_code, 401)


class RefreshTests(APITestCase):
    def setUp(self):
        User.objects.create_user(
            username="member1", email="member1@example.com", password="pw-pw-pw-pw"
        )
        self.tokens = self.client.post(
            reverse("accounts:login"), {"username": "member1", "password": "pw-pw-pw-pw"}
        ).json()

    def test_refresh_returns_a_new_access_token(self):
        response = self.client.post(
            reverse("accounts:refresh"), {"refresh": self.tokens["refresh"]}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.json())

    def test_refresh_rotates_the_refresh_token(self):
        body = self.client.post(
            reverse("accounts:refresh"), {"refresh": self.tokens["refresh"]}
        ).json()
        self.assertIn("refresh", body)
        self.assertNotEqual(body["refresh"], self.tokens["refresh"])

    def test_garbage_refresh_token_is_rejected(self):
        response = self.client.post(reverse("accounts:refresh"), {"refresh": "not-a-token"})
        self.assertEqual(response.status_code, 401)


class MeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="admin1",
            email="admin1@example.com",
            password="pw-pw-pw-pw",
            role=Role.ADMIN,
        )
        self.access = self.client.post(
            reverse("accounts:login"), {"username": "admin1", "password": "pw-pw-pw-pw"}
        ).json()["access"]

    def test_me_requires_authentication(self):
        self.assertEqual(self.client.get(reverse("accounts:me")).status_code, 401)

    def test_me_rejects_a_malformed_bearer_token(self):
        self.client.credentials(HTTP_AUTHORIZATION="Bearer nonsense")
        self.assertEqual(self.client.get(reverse("accounts:me")).status_code, 401)

    def test_me_returns_the_authenticated_user(self):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        body = self.client.get(reverse("accounts:me")).json()
        self.assertEqual(body["username"], "admin1")
        self.assertEqual(body["role"], Role.ADMIN)

    def test_me_reflects_a_role_change_without_a_new_token(self):
        """Authorisation reads the database, so the token's claim cannot go stale."""
        self.user.role = Role.MEMBER
        self.user.save()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.access}")
        self.assertEqual(self.client.get(reverse("accounts:me")).json()["role"], Role.MEMBER)
