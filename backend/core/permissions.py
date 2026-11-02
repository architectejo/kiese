"""
RBAC permissions for ETS. KIESE.
Enforces role-based and node-scoped access control.
"""

from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Only ADMIN users (or Django superuser)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role == 'ADMIN'
        )


class IsDirection(BasePermission):
    """ADMIN or DIRECTION users (or Django superuser)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in ('ADMIN', 'DIRECTION')
        )


class IsHeadquarters(BasePermission):
    """ADMIN, DIRECTION, or COMPTABLE — HQ-level access (or Django superuser)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.is_headquarters
        )


class IsGerant(BasePermission):
    """GERANT or higher (or Django superuser)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in (
                'ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'
            )
        )


class IsFacturier(BasePermission):
    """FACTURIER or higher (GERANT+) (or Django superuser)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in (
                'ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER'
            )
        )


class IsLivreur(BasePermission):
    """LIVREUR or higher (or Django superuser)."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in (
                'ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'LIVREUR'
            )
        )


class IsFacturierOrLivreur(BasePermission):
    """FACTURIER or LIVREUR (or higher) (or Django superuser).
    Used for delivery confirmation: the facturier prints & hands receipt to the livreur."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and (
            request.user.is_superuser or request.user.role in (
                'ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT', 'FACTURIER', 'LIVREUR'
            )
        )


class NodeScopedPermission(BasePermission):
    """
    Ensures that non-HQ users can only access data from their assigned node.
    Views must set `node_field` attribute (default: 'node') indicating
    the field name on the model that references the Node.
    """

    def has_object_permission(self, request, view, obj):
        if request.user.can_access_all_nodes:
            return True

        node_field = getattr(view, 'node_field', 'node')
        obj_node = getattr(obj, node_field, None)

        if obj_node is None:
            return True

        # Compare node objects or node IDs
        user_node = request.user.node
        if user_node is None:
            return False

        if hasattr(obj_node, 'pk'):
            return obj_node.pk == user_node.pk
        return obj_node == user_node.pk
