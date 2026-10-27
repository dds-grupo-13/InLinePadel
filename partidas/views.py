from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from clubes.models import Club, Turno
from config.exceptions import Conflicto
from config.permissions import EsAdminClub, EsJugador
from social.models import Invitacion
from social.notificaciones import notificar

from .filters import LobbyFilter
from .models import Inscripcion, Lobby
from .serializers import (
    InscripcionSerializer,
    LobbySerializer,
    ProximoLobbySerializer,
)


class LobbyViewSet(viewsets.ModelViewSet):
    serializer_class = LobbySerializer
    filterset_class = LobbyFilter
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action == "check_in":
            return [EsAdminClub()]
        return [IsAuthenticated(), EsJugador()]

    def get_queryset(self):
        jugador = self.request.user.jugador
        propios = Inscripcion.objects.filter(lobby=OuterRef("pk"), jugador=jugador)
        invitado = Invitacion.objects.filter(
            lobby=OuterRef("pk"),
            receptor=jugador,
            estado=Invitacion.Estado.PENDIENTE,
        )
        return (
            Lobby.objects.select_related(
                "turno", "turno__cancha", "turno__cancha__club", "capitan__usuario"
            )
            .prefetch_related("inscripciones__jugador__usuario")
            .annotate(
                ocupados=Count("inscripciones", distinct=True),
                es_mio=Exists(propios),
                es_invitado=Exists(invitado),
            )
            .filter(
                Q(es_mio=True)
                | (
                    Q(
                        estado=Lobby.Estado.EN_FORMACION,
                        turno__inicio__gt=timezone.now(),
                        turno__cancha__club__estado=Club.Estado.ACTIVO,
                    )
                    & (
                        Q(privacidad=Lobby.Privacidad.PUBLICO)
                        | Q(es_invitado=True)
                    )
                )
            )
            .order_by("turno__inicio", "pk")
        )

    def _responder(self, lobby, codigo=status.HTTP_200_OK):
        lobby = self.get_queryset().get(pk=lobby.pk)
        return Response(self.get_serializer(lobby).data, status=codigo)

    def _exigir_capitan(self, lobby):
        if lobby.capitan_id != self.request.user.pk:
            raise PermissionDenied("Solo el capitán de la partida puede hacer esto.")

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            lobby = serializer.save(capitan=request.user.jugador)
        return self._responder(lobby, status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        lobby = serializer.instance
        self._exigir_capitan(lobby)
        if lobby.estado != Lobby.Estado.EN_FORMACION:
            raise Conflicto("Solo se puede modificar una partida en formación.")
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        return self.cancelar(request, *args, **kwargs)

    @action(detail=False, methods=["get"])
    def resumen_por_club(self, request):
        abiertos = self.filter_queryset(self.get_queryset()).filter(
            estado=Lobby.Estado.EN_FORMACION,
            es_mio=False,
            ocupados__lt=Lobby.CANTIDAD_CUPOS,
        )
        invitado = Invitacion.objects.filter(
            lobby=OuterRef("pk"),
            receptor=request.user.jugador,
            estado=Invitacion.Estado.PENDIENTE,
        )
        base = Lobby.objects.filter(pk__in=abiertos.order_by().values("pk")).annotate(
            es_invitado=Exists(invitado)
        )
        proximo = base.filter(turno__cancha__club=OuterRef("club")).order_by(
            "turno__inicio", "pk"
        )
        filas = list(
            base.order_by()
            .values(club=F("turno__cancha__club"))
            .annotate(
                disponibles=Count("pk", distinct=True),
                cupos_libres=Lobby.CANTIDAD_CUPOS * Count("pk", distinct=True)
                - Count("inscripciones"),
                invitaciones=Count("pk", filter=Q(es_invitado=True), distinct=True),
                proximo_id=Subquery(proximo.values("pk")[:1]),
            )
            .order_by("club")
        )
        proximos = Lobby.objects.select_related("turno").in_bulk(
            [f["proximo_id"] for f in filas]
        )
        return Response(
            [
                {
                    "club": f["club"],
                    "disponibles": f["disponibles"],
                    "cupos_libres": f["cupos_libres"],
                    "invitaciones": f["invitaciones"],
                    "proximo": ProximoLobbySerializer(proximos[f["proximo_id"]]).data,
                }
                for f in filas
            ]
        )

    @action(detail=True, methods=["post"])
    def cancelar(self, request, *args, **kwargs):
        lobby = self.get_object()
        self._exigir_capitan(lobby)
        try:
            lobby.cancelar()
        except ValueError as e:
            raise Conflicto(str(e))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def unirse(self, request, pk=None):
        lobby = self.get_object()
        jugador = request.user.jugador
        if lobby.inscripciones.filter(jugador=jugador).exists():
            return Response(
                {"detail": "Ya estás inscripto en esta partida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if lobby.estado != Lobby.Estado.EN_FORMACION or lobby.ocupados >= Lobby.CANTIDAD_CUPOS:
            raise Conflicto("El partido ya está completo.")

        invitacion = lobby.invitaciones.filter(
            receptor=jugador, estado=Invitacion.Estado.PENDIENTE
        ).first()
        if lobby.privacidad == Lobby.Privacidad.PRIVADO and invitacion is None:
            raise PermissionDenied("Esta partida es solo por invitación.")

        with transaction.atomic():
            if invitacion is not None:
                invitacion.aceptar()
            else:
                lobby.inscribir(jugador)
        otros = [
            i.jugador.usuario_id
            for i in lobby.inscripciones.select_related("jugador")
            if i.jugador_id != jugador.pk
        ]
        notificar(otros, f"{request.user.username} se unió a tu partida.")
        return self._responder(lobby)

    @action(detail=True, methods=["post"])
    def abandonar(self, request, pk=None):
        lobby = self.get_object()
        jugador = request.user.jugador
        lobby.abandonar(jugador)
        otros = list(
            lobby.inscripciones.values_list("jugador__usuario_id", flat=True)
        )
        notificar(otros, f"{request.user.username} abandonó la partida.")
        return Response({"detail": "Abandonaste la partida."})

    @action(detail=False, methods=["post"])
    def check_in(self, request):
        if not isinstance(request.data, dict):
            raise ValidationError({"codigo_reserva": "Este campo es obligatorio."})
        codigo = str(request.data.get("codigo_reserva", "")).strip().upper()
        lobbies = Lobby.objects.select_related("turno__cancha__club").filter(
            codigo_reserva=codigo
        )
        if not request.user.is_superuser:
            lobbies = lobbies.filter(turno__cancha__club__admin=request.user)
        lobby = lobbies.first()
        if lobby is None:
            return Response(
                {"detail": "El código de reserva no es válido para este club."},
                status=status.HTTP_404_NOT_FOUND,
            )
        habilitado_desde = lobby.fecha_check_in - timedelta(
            minutes=Lobby.MINUTOS_ANTICIPO_CHECK_IN
        )
        if timezone.now() < habilitado_desde:
            hora = timezone.localtime(habilitado_desde)
            raise Conflicto(
                f"El check-in se habilita el {hora:%d/%m} a las {hora:%H:%M}."
            )
        with transaction.atomic():
            pasado = Lobby.objects.filter(pk=lobby.pk, estado=Lobby.Estado.COMPLETO).update(
                estado=Lobby.Estado.JUGADO
            )
            if not pasado:
                raise Conflicto("Esta reserva ya fue utilizada o no está confirmada.")
            Turno.objects.filter(pk=lobby.turno_id).update(estado=Turno.Estado.CUMPLIDO)
        return Response({"detail": "Check-in registrado.", "lobby": lobby.pk})


class InscripcionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InscripcionSerializer
    permission_classes = [IsAuthenticated, EsJugador]
    filterset_fields = ["lobby"]

    def get_queryset(self):
        return Inscripcion.objects.select_related("jugador__usuario").filter(
            jugador=self.request.user.jugador
        )
