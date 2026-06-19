"""Role-based DRF permissions."""
from rest_framework.permissions import BasePermission

from accounts.models import User


class _RolePermission(BasePermission):
    role = None

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role == self.role
        )


class IsPassenger(_RolePermission):
    role = User.Roles.PASSENGER


class IsDriver(_RolePermission):
    role = User.Roles.DRIVER


class IsOperator(_RolePermission):
    role = User.Roles.OPERATOR


class IsAdmin(_RolePermission):
    role = User.Roles.ADMIN
