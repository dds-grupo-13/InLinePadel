from django.contrib.auth import authenticate
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
    scope = "login"
    cache_key_prefix = "login"

    def parse_rate(self, rate):
        return 10, 15 * 60

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }


class AuthViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], throttle_classes=[LoginRateThrottle])
    def login(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        usuario = authenticate(request, **serializer.validated_data)
        if usuario is None:
            return Response(
                {"detail": "Usuario o contraseña incorrectos."},
                status=status.HTTP_400_BAD_REQUEST,
            )
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
