from datetime import timedelta

from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from clubes.models import Club, Turno
from config.exceptions import Conflicto
from config.permissions import EsAdminClub, EsJugador
from social.models import Contacto, Invitacion
from social.serializers import InvitacionSerializer
from social.notificaciones import notificar

from .filters import LobbyFilter
from .models import Inscripcion, Lobby
from .serializers import (
    CederLugarSerializer,
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

    def _queryset_base(self):
        """Todos los lobbies, con las anotaciones del jugador, sin filtrar visibilidad."""
        jugador = self.request.user.jugador
        propios = Inscripcion.objects.filter(lobby=OuterRef("pk"), jugador=jugador)
        invitado = Invitacion.objects.filter(
            lobby=OuterRef("pk"),
            receptor=jugador,
            estado=Invitacion.Estado.PENDIENTE,
        )
        cesion = Invitacion.objects.filter(
            lobby=OuterRef("pk"),
            receptor=jugador,
            estado=Invitacion.Estado.PENDIENTE,
            reemplaza__isnull=False,
        )
        return (
            Lobby.objects.select_related(
                "turno", "turno__cancha", "turno__cancha__club", "capitan__usuario"
            )
            .prefetch_related(
                "inscripciones__jugador__usuario",
                Prefetch(
                    "invitaciones",
                    queryset=Invitacion.objects.filter(
                        reemplaza=jugador, estado=Invitacion.Estado.PENDIENTE
                    ),
                    to_attr="mis_cesiones",
                ),
            )
            .annotate(
                ocupados=Count("inscripciones", distinct=True),
                es_mio=Exists(propios),
                es_invitado=Exists(invitado),
                tiene_cesion=Exists(cesion),
            )
            .order_by("turno__inicio", "pk")
        )

    def get_queryset(self):
        ahora = timezone.now()
        return self._queryset_base().filter(
            Q(es_mio=True)
            | Q(tiene_cesion=True)
            | (
                Q(
                    estado=Lobby.Estado.EN_FORMACION,
                    plazo_limite__gte=ahora,
                    turno__inicio__gt=ahora,
                    turno__cancha__club__estado=Club.Estado.ACTIVO,
                )
                & (Q(privacidad=Lobby.Privacidad.PUBLICO) | Q(es_invitado=True))
            )
        )

    def _lobby_para_unirse(self):
        # Respeta la privacidad pero no el estado: quien pierde la carrera por el
        # último cupo tiene que recibir 409 y no 404. Un lobby privado sigue
        # oculto salvo para sus inscriptos y para quien fue invitado alguna vez.
        jugador = self.request.user.jugador
        con_invitacion = Invitacion.objects.filter(lobby=OuterRef("pk"), receptor=jugador)
        visibles = self._queryset_base().annotate(tuvo_invitacion=Exists(con_invitacion)).filter(
            Q(es_mio=True)
            | Q(tiene_cesion=True)
            | Q(tuvo_invitacion=True)
            | Q(privacidad=Lobby.Privacidad.PUBLICO)
        )
        lobby = get_object_or_404(visibles, pk=self.kwargs["pk"])
        self.check_object_permissions(self.request, lobby)
        return lobby

    def _vencer_o_409(self, lobby):
        # Antes de cualquier `atomic` de la vista: si no, el 409 revertiría el vencimiento.
        if lobby.vencer_si_corresponde():
            raise Conflicto(
                "Venció el plazo para completar la partida: se canceló y el turno quedó libre."
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
        self._vencer_o_409(lobby)
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
        self._vencer_o_409(lobby)
        try:
            lobby.cancelar_por_capitan(request.user.jugador)
        except Conflicto:
            raise
        except ValueError as e:
            raise Conflicto(str(e))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def unirse(self, request, pk=None):
        lobby = self._lobby_para_unirse()
        self._vencer_o_409(lobby)
        jugador = request.user.jugador
        if lobby.inscripciones.filter(jugador=jugador).exists():
            return Response(
                {"detail": "Ya estás inscripto en esta partida."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if lobby.estado == Lobby.Estado.CANCELADO:
            raise Conflicto("La partida fue cancelada.")
        if (
            lobby.estado in (Lobby.Estado.COMPLETO, Lobby.Estado.JUGADO)
            or lobby.ocupados >= Lobby.CANTIDAD_CUPOS
        ):
            raise Conflicto("El partido ya está completo.")
        if lobby.turno.inicio <= timezone.now():
            raise Conflicto("La partida ya comenzó.")
        if lobby.turno.cancha.club.estado != Club.Estado.ACTIVO:
            raise Conflicto("El club no está recibiendo reservas en este momento.")

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
    def ceder(self, request, pk=None):
        lobby = self.get_object()
        emisor = request.user.jugador
        entrada = CederLugarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        receptor = entrada.validated_data["receptor"]
        if receptor.pk == emisor.pk:
            raise ValidationError("No podés cederte el lugar a vos mismo.")
        with transaction.atomic():
            bloqueado = Lobby.objects.select_for_update().get(pk=lobby.pk)
            if bloqueado.estado != Lobby.Estado.COMPLETO:
                raise Conflicto("Solo se puede ceder el lugar en una partida completa.")
            turno = lobby.turno
            if timezone.now() >= turno.inicio:
                raise Conflicto("La partida ya comenzó.")
            if not lobby.inscripciones.filter(jugador=emisor).exists():
                raise PermissionDenied("Solo un jugador inscripto puede ceder su lugar.")
            if not Contacto.son_contactos(emisor, receptor):
                raise Conflicto("Solo podés ceder tu lugar a jugadores de tu lista de contactos.")
            if lobby.inscripciones.filter(jugador=receptor).exists():
                raise Conflicto("Ese jugador ya está inscripto en la partida.")
            superpuesto = Lobby.conflicto_horario(receptor, turno, excluir_lobby=lobby.pk)
            if superpuesto:
                raise Conflicto(
                    "Ese jugador ya participa de otra partida en ese horario "
                    f"({timezone.localtime(superpuesto.turno.inicio):%d/%m %H:%M})."
                )
            if lobby.invitaciones.filter(
                reemplaza=emisor, estado=Invitacion.Estado.PENDIENTE
            ).exists():
                raise Conflicto("Ya ofreciste tu lugar: esperá la respuesta.")
            invitacion = Invitacion(
                lobby=lobby, emisor=emisor, receptor=receptor, reemplaza=emisor
            )
            invitacion.save()
        club = turno.cancha.club
        notificar(
            [receptor.usuario_id],
            f"{request.user.username} te ofrece su lugar en la partida del "
            f"{turno.fecha:%d/%m} {turno.hora_inicio:%H:%M} en {club.denominacion}. "
            f"La reserva está confirmada; tu parte es ${turno.precio / Lobby.CANTIDAD_CUPOS:.2f}.",
        )
        return Response(InvitacionSerializer(invitacion).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def abandonar(self, request, pk=None):
        lobby = self.get_object()
        jugador = request.user.jugador
        self._vencer_o_409(lobby)
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
            lobby._expirar_pendientes()
        return Response({"detail": "Check-in registrado.", "lobby": lobby.pk})


class InscripcionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = InscripcionSerializer
    permission_classes = [IsAuthenticated, EsJugador]
    filterset_fields = ["lobby"]

    def get_queryset(self):
        return Inscripcion.objects.select_related("jugador__usuario").filter(
            jugador=self.request.user.jugador
        )
