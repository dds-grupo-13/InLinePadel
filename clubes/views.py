from django.db import transaction
from django.db.models import Exists, OuterRef, Prefetch, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from config.exceptions import Conflicto, ErrorDominio
from config.permissions import EsAdminClub, EsAdminSistema, SoloLecturaOAdminSistema
from partidas.models import Lobby

from .filters import TurnoFilter
from .models import Cancha, Club, Turno, Zona
from .serializers import (
    CanchaSerializer,
    CancelacionClubSerializer,
    ClubSerializer,
    TurnoOcupacionSerializer,
    TurnoSerializer,
    ZonaSerializer,
)


class ZonaViewSet(viewsets.ModelViewSet):
    queryset = Zona.objects.all().order_by("nombre")
    serializer_class = ZonaSerializer
    permission_classes = [SoloLecturaOAdminSistema]
    pagination_class = None


class ClubViewSet(viewsets.ModelViewSet):
    serializer_class = ClubSerializer
    filterset_fields = ["zona", "estado"]

    def get_permissions(self):
        if self.action == "ocupacion":
            return [EsAdminClub()]
        if self.action in ("list", "retrieve"):
            return [IsAuthenticated()]
        return [EsAdminSistema()]

    def get_queryset(self):
        qs = Club.objects.select_related("zona").order_by("denominacion")
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.is_staff:
            return qs.filter(admin=user)
        return qs.filter(estado=Club.Estado.ACTIVO)

    def _cambiar_estado(self, estado):
        club = self.get_object()
        club.estado = estado
        club.save(update_fields=["estado"])
        return Response(self.get_serializer(club).data)

    @action(detail=True, methods=["post"])
    def suspender(self, request, pk=None):
        return self._cambiar_estado(Club.Estado.SUSPENDIDO)

    @action(detail=True, methods=["post"])
    def reactivar(self, request, pk=None):
        return self._cambiar_estado(Club.Estado.ACTIVO)

    @action(detail=True, methods=["post"])
    def dar_de_baja(self, request, pk=None):
        return self._cambiar_estado(Club.Estado.BAJA)

    def perform_destroy(self, instance):
        instance.estado = Club.Estado.BAJA
        instance.save(update_fields=["estado"])

    @action(detail=True, methods=["get"])
    def ocupacion(self, request, pk=None):
        club = self.get_object()
        turnos = (
            Turno.objects.con_cancha()
            .filter(cancha__club=club)
            .prefetch_related(
                Prefetch(
                    "lobbies",
                    queryset=Lobby.objects.prefetch_related("inscripciones"),
                )
            )
        )
        turnos = TurnoFilter(request.query_params, queryset=turnos, request=request).qs
        pagina = self.paginate_queryset(turnos)
        serializer = TurnoOcupacionSerializer(pagina, many=True)
        return self.get_paginated_response(serializer.data)


class CanchaViewSet(viewsets.ModelViewSet):
    serializer_class = CanchaSerializer
    filterset_fields = ["club", "tipo", "activa"]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [EsAdminClub()]

    def get_queryset(self):
        qs = Cancha.objects.con_club().order_by("club", "numero")
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.is_staff:
            return qs.filter(club__admin=user)
        return qs.filter(activa=True, club__estado=Club.Estado.ACTIVO)

    def perform_destroy(self, instance):
        if instance.turnos.exists():
            instance.activa = False
            instance.save(update_fields=["activa"])
        else:
            instance.delete()


class TurnoViewSet(viewsets.ModelViewSet):
    serializer_class = TurnoSerializer
    filterset_class = TurnoFilter
    EDITABLES = (Turno.Estado.LIBRE, Turno.Estado.NO_DISPONIBLE)
    MAX_TURNOS_MASIVO = 500

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [EsAdminClub()]

    def get_queryset(self):
        ahora = timezone.now()
        vencido = Lobby.objects.filter(Lobby.q_vencido(ahora), turno=OuterRef("pk"))
        qs = Turno.objects.con_cancha().annotate(liberable=Exists(vencido))
        user = self.request.user
        if user.is_superuser:
            return qs
        if user.is_staff:
            return qs.filter(cancha__club__admin=user)
        # Un turno bloqueado por un lobby vencido ya está libre para el jugador.
        return qs.filter(
            Q(estado=Turno.Estado.LIBRE)
            | Q(estado=Turno.Estado.BLOQUEADO, liberable=True),
            cancha__activa=True,
            cancha__club__estado=Club.Estado.ACTIVO,
            inicio__gt=ahora,
        )

    def _verificar_editable(self, turno):
        if turno.estado not in self.EDITABLES:
            raise Conflicto("El turno ya fue tomado por una partida y no puede modificarse.")

    def perform_update(self, serializer):
        self._verificar_editable(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self._verificar_editable(instance)
        if instance.lobbies.exists():
            raise Conflicto("El turno tiene historial de partidas y no puede eliminarse.")
        instance.delete()

    def _transicion(self, origen, destino, mensaje):
        turno = self.get_object()
        cambiado = Turno.objects.filter(pk=turno.pk, estado=origen).update(estado=destino)
        if not cambiado:
            raise Conflicto(mensaje)
        turno.refresh_from_db()
        return Response(self.get_serializer(turno).data)

    @action(detail=True, methods=["post"])
    def no_disponible(self, request, pk=None):
        # Si el turno lo bloquea un lobby vencido, se libera antes de retirarlo.
        Lobby.vencer_del_turno(self.get_object())
        return self._transicion(
            Turno.Estado.LIBRE,
            Turno.Estado.NO_DISPONIBLE,
            "Solo se puede retirar un turno libre: este ya fue tomado o ya está retirado.",
        )

    @action(detail=True, methods=["post"])
    def disponible(self, request, pk=None):
        return self._transicion(
            Turno.Estado.NO_DISPONIBLE,
            Turno.Estado.LIBRE,
            "Solo se puede volver a publicar un turno marcado como no disponible.",
        )

    @action(detail=True, methods=["post"])
    def cancelar_por_club(self, request, pk=None):
        turno = self.get_object()
        entrada = CancelacionClubSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        if turno.inicio <= timezone.now():
            raise ErrorDominio("El turno ya comenzó o ya pasó.")
        with transaction.atomic():
            lobby = (
                Lobby.objects.select_for_update()
                .filter(
                    turno=turno,
                    estado__in=(Lobby.Estado.EN_FORMACION, Lobby.Estado.COMPLETO),
                )
                .first()
            )
            if lobby is None:
                raise Conflicto(
                    "Este turno no tiene una partida para cancelar; "
                    "podés retirarlo con 'No disponible'."
                )
            lobby._cancelar(
                Lobby.CanceladaPor.CLUB,
                entrada.validated_data["motivo"],
                Turno.Estado.NO_DISPONIBLE,
            )
        turno.refresh_from_db()
        return Response(self.get_serializer(turno).data)

    @action(detail=False, methods=["post"])
    def crear_masivo(self, request):
        if isinstance(request.data, list) and len(request.data) > self.MAX_TURNOS_MASIVO:
            raise ValidationError(
                f"Se pueden crear hasta {self.MAX_TURNOS_MASIVO} turnos por pedido."
            )
        serializer = self.get_serializer(data=request.data, many=True)
        serializer.is_valid(raise_exception=True)
        turnos = [Turno(**datos) for datos in serializer.validated_data]
        with transaction.atomic():
            creados = Turno.objects.crear_masivo(turnos)
        return Response(self.get_serializer(creados, many=True).data, status=status.HTTP_201_CREATED)
