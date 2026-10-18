from rest_framework.permissions import SAFE_METHODS, BasePermission


class EsAdminSistema(BasePermission):
    message = "Solo el administrador del sistema puede realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)


class EsAdminClub(BasePermission):
    message = "Solo el administrador de un club puede realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and user.is_staff)


class EsJugador(BasePermission):
    message = "Necesitás un perfil de jugador para realizar esta acción."

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and hasattr(user, "jugador")
        )


class SoloLecturaOAdminSistema(BasePermission):
    """Lectura para cualquiera (autenticado o no); escritura solo admin del sistema."""

    message = "Solo el administrador del sistema puede modificar este recurso."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        return bool(user and user.is_authenticated and user.is_superuser)
