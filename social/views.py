from django.db import transaction
from django.db.models import Q
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from config.exceptions import Conflicto
from config.permissions import EsJugador
from partidas.models import Lobby

from .models import Contacto, Invitacion, Notificacion, SolicitudAcceso
from .notificaciones import notificar
from .serializers import (
    ContactoSerializer,
    InvitacionSerializer,
    NotificacionSerializer,
    SolicitudAccesoSerializer,
)


class _JugadorViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated, EsJugador]

    @property
    def jugador(self):
        return self.request.user.jugador


class ContactoViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    _JugadorViewSet,
):
    serializer_class = ContactoSerializer
    filterset_fields = ["estado"]

    def get_queryset(self):
        return Contacto.objects.select_related(
            "jugador__usuario", "contacto__usuario"
        ).filter(Q(jugador=self.jugador) | Q(contacto=self.jugador))

    def perform_create(self, serializer):
        destino = serializer.validated_data["contacto"]
        if destino.pk == self.jugador.pk:
            raise ValidationError("No podés agregarte a vos mismo.")
        if Contacto.objects.filter(
            Q(jugador=self.jugador, contacto=destino)
            | Q(jugador=destino, contacto=self.jugador)
        ).exists():
            raise ValidationError("Ya existe una solicitud o un contacto con ese jugador.")
        contacto = serializer.save(jugador=self.jugador)
        notificar(
            [contacto.contacto.usuario_id],
            f"{self.request.user.username} te envió una solicitud de contacto.",
        )

    def _responder_solicitud(self, estado):
        contacto = self.get_object()
        if contacto.contacto_id != self.jugador.pk:
            raise PermissionDenied("Solo quien recibe la solicitud puede responderla.")
        cambiado = Contacto.objects.filter(
            pk=contacto.pk, estado=Contacto.Estado.PENDIENTE
        ).update(estado=estado)
        if not cambiado:
            raise Conflicto("La solicitud ya fue respondida.")
        contacto.refresh_from_db()
        accion = "aceptó" if estado == Contacto.Estado.ACEPTADO else "rechazó"
        notificar(
            [contacto.jugador.usuario_id],
            f"{self.request.user.username} {accion} tu solicitud de contacto.",
        )
        return Response(self.get_serializer(contacto).data)

    @action(detail=True, methods=["post"])
    def aceptar(self, request, pk=None):
        return self._responder_solicitud(Contacto.Estado.ACEPTADO)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        return self._responder_solicitud(Contacto.Estado.RECHAZADO)


class InvitacionViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    _JugadorViewSet,
):
    serializer_class = InvitacionSerializer
    filterset_fields = ["lobby", "estado"]

    def get_queryset(self):
        qs = Invitacion.objects.select_related("emisor__usuario", "receptor__usuario", "lobby")
        qs = qs.filter(Q(emisor=self.jugador) | Q(receptor=self.jugador))
        rol = self.request.query_params.get("rol")
        if rol == "enviadas":
            qs = qs.filter(emisor=self.jugador)
        elif rol == "recibidas":
            qs = qs.filter(receptor=self.jugador)
        return qs

    def perform_create(self, serializer):
        receptor = serializer.validated_data["receptor"]
        lobby = serializer.validated_data["lobby"]
        es_contacto = Contacto.son_contactos(self.jugador, receptor)
        if not es_contacto:
            raise Conflicto("Solo podés invitar a jugadores de tu lista de contactos.")
        if lobby.inscripciones.count() >= Lobby.CANTIDAD_CUPOS:
            raise Conflicto("El partido ya está completo.")
        if lobby.vencer_si_corresponde():
            raise Conflicto("Venció el plazo para completar la partida.")
        invitacion = serializer.save(emisor=self.jugador)
        notificar(
            [receptor.usuario_id],
            f"{self.request.user.username} te invitó a una partida.",
        )
        return invitacion

    def _como_receptor(self):
        invitacion = self.get_object()
        if invitacion.receptor_id != self.jugador.pk:
            raise PermissionDenied("Solo quien recibió la invitación puede responderla.")
        return invitacion

    @action(detail=True, methods=["post"])
    def aceptar(self, request, pk=None):
        invitacion = self._como_receptor()
        if not invitacion.es_cesion and invitacion.lobby.vencer_si_corresponde():
            # El vencimiento ya la dejó EXPIRADA (_expirar_pendientes).
            raise Conflicto("Venció el plazo para completar la partida.")
        try:
            with transaction.atomic():
                invitacion.aceptar()
        except Conflicto:
            Invitacion.objects.filter(
                pk=invitacion.pk, estado=Invitacion.Estado.PENDIENTE
            ).update(estado=Invitacion.Estado.EXPIRADA)
            raise
        notificar(
            [invitacion.emisor.usuario_id],
            f"{request.user.username} aceptó tu invitación.",
        )
        invitacion.refresh_from_db()
        return Response(self.get_serializer(invitacion).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        invitacion = self._como_receptor()
        try:
            invitacion.rechazar()
        except ValueError as e:
            raise Conflicto(str(e))
        notificar(
            [invitacion.emisor.usuario_id],
            f"{request.user.username} rechazó tu invitación.",
        )
        return Response(self.get_serializer(invitacion).data)


class SolicitudAccesoViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    _JugadorViewSet,
):
    serializer_class = SolicitudAccesoSerializer
    filterset_fields = ["lobby", "estado"]

    def get_queryset(self):
        return SolicitudAcceso.objects.select_related(
            "jugador__usuario", "lobby"
        ).filter(Q(jugador=self.jugador) | Q(lobby__capitan=self.jugador))

    def _como_capitan(self):
        solicitud = self.get_object()
        if solicitud.lobby.capitan_id != self.jugador.pk:
            raise PermissionDenied("Solo el capitán puede responder la solicitud.")
        return solicitud

    @action(detail=True, methods=["post"])
    def aceptar(self, request, pk=None):
        solicitud = self._como_capitan()
        try:
            with transaction.atomic():
                solicitud.aceptar()
        except Conflicto:
            SolicitudAcceso.objects.filter(
                pk=solicitud.pk, estado=SolicitudAcceso.Estado.PENDIENTE
            ).update(estado=SolicitudAcceso.Estado.EXPIRADA)
            raise
        notificar([solicitud.jugador.usuario_id], "Tu solicitud fue aceptada: ya sos parte de la partida.")
        solicitud.refresh_from_db()
        return Response(self.get_serializer(solicitud).data)

    @action(detail=True, methods=["post"])
    def rechazar(self, request, pk=None):
        solicitud = self._como_capitan()
        try:
            solicitud.rechazar()
        except ValueError as e:
            raise Conflicto(str(e))
        notificar([solicitud.jugador.usuario_id], "El capitán rechazó tu solicitud de acceso.")
        return Response(self.get_serializer(solicitud).data)


class NotificacionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificacionSerializer
    filterset_fields = ["leida"]

    def get_queryset(self):
        return Notificacion.objects.filter(usuario=self.request.user)

    @action(detail=True, methods=["post"])
    def marcar_leida(self, request, pk=None):
        notificacion = self.get_object()
        Notificacion.objects.filter(pk=notificacion.pk).update(leida=True)
        notificacion.leida = True
        return Response(self.get_serializer(notificacion).data)

    @action(detail=False, methods=["post"])
    def marcar_todas_leidas(self, request):
        marcadas = self.get_queryset().filter(leida=False).update(leida=True)
        return Response({"marcadas": marcadas})
