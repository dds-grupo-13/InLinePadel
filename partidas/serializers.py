from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import serializers

from clubes.models import Turno
from clubes.serializers import TurnoSerializer
from config.exceptions import Conflicto
from usuarios.serializers import JugadorPublicoSerializer

from .models import Inscripcion, Lobby


class InscripcionSerializer(serializers.ModelSerializer):
    jugador = JugadorPublicoSerializer(read_only=True)

    class Meta:
        model = Inscripcion
        fields = ["id", "lobby", "jugador", "numero_cupo", "fecha_inscripcion"]
        read_only_fields = fields


class ProximoLobbySerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk")
    fecha = serializers.DateField(source="turno.fecha")
    hora_inicio = serializers.TimeField(source="turno.hora_inicio")
    inicio = serializers.DateTimeField(source="turno.inicio")


class LobbySerializer(serializers.ModelSerializer):
    turno = serializers.PrimaryKeyRelatedField(queryset=Turno.objects.con_cancha())
    turno_detalle = TurnoSerializer(source="turno", read_only=True)
    inscripciones = InscripcionSerializer(many=True, read_only=True)
    cupos_ocupados = serializers.SerializerMethodField()
    cupos_libres = serializers.SerializerMethodField()
    precio_total = serializers.DecimalField(
        source="turno.precio", max_digits=10, decimal_places=2, read_only=True
    )
    precio_por_jugador = serializers.SerializerMethodField()
    estado_reserva = serializers.SerializerMethodField()
    mensaje_reserva = serializers.SerializerMethodField()
    es_capitan = serializers.SerializerMethodField()
    fui_invitado = serializers.SerializerMethodField()
    cierre = serializers.SerializerMethodField()
    reserva_firme = serializers.SerializerMethodField()
    puede_cancelar = serializers.SerializerMethodField()
    puede_abandonar = serializers.SerializerMethodField()
    aviso_cierre = serializers.SerializerMethodField()

    class Meta:
        model = Lobby
        fields = [
            "id", "privacidad", "estado", "fecha_creacion", "plazo_limite",
            "fecha_check_in", "capitan", "es_capitan", "fui_invitado", "turno",
            "turno_detalle", "inscripciones", "cupos_ocupados", "cupos_libres",
            "precio_total", "precio_por_jugador", "estado_reserva",
            "mensaje_reserva", "codigo_reserva", "cierre", "reserva_firme",
            "puede_cancelar", "puede_abandonar", "cancelada_por",
            "motivo_cancelacion", "aviso_cierre",
        ]
        read_only_fields = [
            "estado", "fecha_creacion", "plazo_limite", "fecha_check_in",
            "capitan", "codigo_reserva", "cancelada_por", "motivo_cancelacion",
        ]

    def _jugador(self):
        request = self.context.get("request")
        return getattr(getattr(request, "user", None), "jugador", None)

    def _ocupados(self, lobby):
        return len(lobby.inscripciones.all())

    def _inscripto(self, lobby):
        jugador = self._jugador()
        return bool(jugador) and any(
            i.jugador_id == jugador.pk for i in lobby.inscripciones.all()
        )

    def get_cupos_ocupados(self, lobby):
        return self._ocupados(lobby)

    def get_cupos_libres(self, lobby):
        return Lobby.CANTIDAD_CUPOS - self._ocupados(lobby)

    def get_precio_por_jugador(self, lobby):
        return f"{lobby.turno.precio / Lobby.CANTIDAD_CUPOS:.2f}"

    def get_es_capitan(self, lobby):
        jugador = self._jugador()
        return bool(jugador) and lobby.capitan_id == jugador.pk

    def get_fui_invitado(self, lobby):
        return bool(getattr(lobby, "es_invitado", False))

    def get_estado_reserva(self, lobby):
        return lobby.estado_reserva

    def get_cierre(self, lobby):
        return serializers.DateTimeField().to_representation(lobby.cierre)

    def get_reserva_firme(self, lobby):
        return lobby.es_firme()

    def get_puede_cancelar(self, lobby):
        jugador = self._jugador()
        return bool(jugador) and lobby.puede_cancelar(jugador)

    def get_puede_abandonar(self, lobby):
        jugador = self._jugador()
        return bool(jugador) and lobby.puede_abandonar(jugador)

    def get_aviso_cierre(self, lobby):
        cierre = timezone.localtime(lobby.cierre)
        if lobby.estado == Lobby.Estado.COMPLETO:
            if lobby.es_firme():
                return "Reserva firme: ya no se puede bajar nadie."
            return f"Podés bajarte hasta el {cierre:%d/%m} a las {cierre:%H:%M}."
        if (
            lobby.estado == Lobby.Estado.EN_FORMACION
            and timezone.now() >= lobby.cierre
        ):
            return (
                "Partida de último momento: cuando se complete, "
                "la reserva queda firme."
            )
        return None

    def get_mensaje_reserva(self, lobby):
        if lobby.estado == Lobby.Estado.CANCELADO:
            if lobby.cancelada_por == Lobby.CanceladaPor.CLUB:
                return f"Partida cancelada por el club: {lobby.motivo_cancelacion}"
            motivo = {
                Lobby.CanceladaPor.CAPITAN: " por el capitán",
                Lobby.CanceladaPor.ABANDONO: " porque se fueron todos los jugadores",
                Lobby.CanceladaPor.VENCIMIENTO: " por vencimiento del plazo",
            }.get(lobby.cancelada_por, "")
            return f"Partida cancelada{motivo} — el turno quedó libre"
        if lobby.estado == Lobby.Estado.EN_FORMACION:
            faltan = Lobby.CANTIDAD_CUPOS - self._ocupados(lobby)
            vence = timezone.localtime(lobby.plazo_limite)
            return (
                f"Reserva provisoria — faltan {faltan} jugadores, "
                f"vence el {vence:%d/%m} a las {vence:%H:%M}"
            )
        if lobby.estado == Lobby.Estado.JUGADO:
            return "Partido jugado — reserva cumplida"
        if self._inscripto(lobby) and lobby.codigo_reserva:
            return f"Reserva confirmada — código {lobby.codigo_reserva}"
        return "Reserva confirmada"

    def to_representation(self, lobby):
        datos = super().to_representation(lobby)
        if not self._inscripto(lobby):
            datos["codigo_reserva"] = None
        return datos

    def create(self, validated_data):
        turno = validated_data.pop("turno")
        capitan = validated_data.pop("capitan")
        try:
            return Lobby.crear(turno, capitan, **validated_data)
        except Conflicto:
            raise
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

    def update(self, instance, validated_data):
        validated_data.pop("turno", None)
        return super().update(instance, validated_data)
