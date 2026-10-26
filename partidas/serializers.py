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

    class Meta:
        model = Lobby
        fields = [
            "id", "privacidad", "estado", "fecha_creacion", "plazo_limite",
            "fecha_check_in", "capitan", "es_capitan", "fui_invitado", "turno",
            "turno_detalle", "inscripciones", "cupos_ocupados", "cupos_libres",
            "precio_total", "precio_por_jugador", "estado_reserva",
            "mensaje_reserva", "codigo_reserva",
        ]
        read_only_fields = [
            "estado", "fecha_creacion", "plazo_limite", "fecha_check_in",
            "capitan", "codigo_reserva",
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

    def get_mensaje_reserva(self, lobby):
        if lobby.estado == Lobby.Estado.CANCELADO:
            return "Partida cancelada — el turno quedó libre"
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
