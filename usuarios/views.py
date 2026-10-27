from django.contrib.auth import authenticate
from django.core.cache import caches
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.token_blacklist.models import (
    BlacklistedToken,
    OutstandingToken,
)
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Jugador
from .serializers import (
    JugadorPublicoSerializer,
    LoginSerializer,
    RegistroJugadorSerializer,
)


class LoginRateThrottle(SimpleRateThrottle):
    """Limita solo los intentos fallidos, por IP y usuario.

    Un login correcto no cuenta (y reinicia el contador), y los intentos de
    otros usuarios desde la misma IP no se pisan entre sí.
    """

    scope = "login"
    cache_key_prefix = "login"
    MAX_INTENTOS = 10
    VENTANA_SEGUNDOS = 15 * 60

    def __init__(self, request, username):
        self.key = self.cache_format % {
            "scope": self.scope,
            "ident": f"{self.get_ident(request)}:{username.strip().lower()}",
        }
        self.cache = caches["default"]

    def bloqueado(self):
        return self.cache.get(self.key, 0) >= self.MAX_INTENTOS

    def registrar_fallo(self):
        if self.cache.add(self.key, 1, self.VENTANA_SEGUNDOS):
            return
        try:
            self.cache.incr(self.key)
        except ValueError:
            self.cache.set(self.key, 1, self.VENTANA_SEGUNDOS)

    def reiniciar(self):
        self.cache.delete(self.key)


class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], throttle_classes=[])
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        limite = LoginRateThrottle(request, serializer.validated_data["username"])
        if limite.bloqueado():
            return Response(
                {"detail": "Demasiados intentos fallidos. Probá de nuevo en unos minutos."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(limite.VENTANA_SEGUNDOS)},
            )
        usuario = authenticate(request, **serializer.validated_data)
        if usuario is None:
            limite.registrar_fallo()
            return Response(
                {"detail": "Usuario o contraseña incorrectos."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        limite.reiniciar()
        refresh = RefreshToken.for_user(usuario)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "usuario": _perfil(usuario),
            }
        )

    @action(detail=False, methods=["post"])
    def refresh(self, request):
        serializer = TokenRefreshSerializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as e:
            raise InvalidToken(e.args[0])
        return Response(serializer.validated_data)

    @action(detail=False, methods=["post"], permission_classes=[IsAuthenticated])
    def logout(self, request):
        try:
            token = request.data.get("refresh")
            if not token:
                raise TokenError
            RefreshToken(token).blacklist()
        except TokenError:
            return Response(
                {"detail": "Refresh token inválido."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


def _perfil(usuario):
    datos = {
        "id": usuario.pk,
        "username": usuario.username,
        "es_admin_club": usuario.is_staff and not usuario.is_superuser,
        "es_admin_sistema": usuario.is_superuser,
    }
    if hasattr(usuario, "jugador"):
        datos["jugador"] = RegistroJugadorSerializer(usuario.jugador).data
    return datos


class JugadorViewSet(viewsets.ModelViewSet):
    queryset = Jugador.objects.select_related("usuario", "zona").filter(
        usuario__is_active=True
    )
    filterset_fields = ["zona", "posicion"]

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsAuthenticated()]

    def get_serializer_class(self):
        if self.action in ("list",) or (
            self.action == "retrieve" and not self._es_propio()
        ):
            return JugadorPublicoSerializer
        return RegistroJugadorSerializer

    def _es_propio(self):
        return str(self.kwargs.get("pk")) == str(self.request.user.pk)

    def get_queryset(self):
        qs = super().get_queryset()
        if self.action == "list":
            texto = self.request.query_params.get("q")
            if texto:
                qs = qs.filter(usuario__username__icontains=texto)
            return qs.exclude(pk=self.request.user.pk)
        return qs

    def check_object_permissions(self, request, obj):
        super().check_object_permissions(request, obj)
        if self.action != "retrieve" and obj.pk != request.user.pk:
            self.permission_denied(request, message="No podés modificar el perfil de otro jugador.")

    def perform_destroy(self, instance):
        instance.dar_de_baja()
        for token in OutstandingToken.objects.filter(user=instance.usuario):
            BlacklistedToken.objects.get_or_create(token=token)

    @action(detail=False, methods=["get", "patch"])
    def me(self, request):
        jugador = getattr(request.user, "jugador", None)
        if jugador is None:
            return Response(_perfil(request.user))
        if request.method == "PATCH":
            serializer = RegistroJugadorSerializer(
                jugador, data=request.data, partial=True, context={"request": request}
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()
        return Response(_perfil(request.user))
