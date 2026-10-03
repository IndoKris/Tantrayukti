"""Tests for the custom user model and its role helpers."""

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import Role

User = get_user_model()


class UserModelTests(TestCase):
    def test_default_role_is_member(self):
        user = User.objects.create_user(username="m", email="m@example.com", password="pw")
        self.assertEqual(user.role, Role.MEMBER)

    def test_email_is_unique(self):
        User.objects.create_user(username="a", email="dup@example.com", password="pw")
        with self.assertRaises(IntegrityError):
            User.objects.create_user(username="b", email="dup@example.com", password="pw")

    def test_superuser_is_forced_to_admin_role(self):
        """`createsuperuser` must yield a working admin without a separate role edit."""
        root = User.objects.create_superuser(
            username="root", email="root@example.com", password="pw"
        )
        self.assertEqual(root.role, Role.ADMIN)
        self.assertTrue(root.is_admin)

    def test_role_ranking_is_ordered(self):
        member = User(username="m", role=Role.MEMBER)
        manager = User(username="g", role=Role.MANAGER)
        admin = User(username="a", role=Role.ADMIN)
        self.assertLess(member.role_rank, manager.role_rank)
        self.assertLess(manager.role_rank, admin.role_rank)

    def test_has_role_at_least_is_inclusive_upwards(self):
        manager = User(username="g", role=Role.MANAGER)
        self.assertTrue(manager.has_role_at_least(Role.MEMBER))
        self.assertTrue(manager.has_role_at_least(Role.MANAGER))
        self.assertFalse(manager.has_role_at_least(Role.ADMIN))

    def test_member_is_not_manager_or_above(self):
        member = User(username="m", role=Role.MEMBER)
        self.assertFalse(member.is_manager_or_above)
        self.assertFalse(member.is_admin)

    def test_unknown_role_ranks_lowest_and_grants_nothing(self):
        broken = User(username="x", role="not-a-role")
        self.assertEqual(broken.role_rank, 0)
        self.assertFalse(broken.has_role_at_least(Role.MEMBER))
