from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Inscripcion, Lobby


class InscripcionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inscripcion
        fields = ["id", "lobby", "jugador", "numero_cupo", "fecha_inscripcion"]
        read_only_fields = fields


class LobbySerializer(serializers.ModelSerializer):
    inscripciones = InscripcionSerializer(many=True, read_only=True)

    class Meta:
        model = Lobby
        fields = [
            "id", "privacidad", "estado", "fecha_creacion", "plazo_limite",
            "fecha_check_in", "capitan", "turno", "inscripciones",
        ]
        read_only_fields = ["estado", "fecha_creacion", "capitan"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        plazo = attrs.get("plazo_limite", getattr(self.instance, "plazo_limite", None))
        check_in = attrs.get("fecha_check_in", getattr(self.instance, "fecha_check_in", None))
        if plazo and check_in and plazo > check_in:
            raise serializers.ValidationError(
                "El plazo límite debe ser anterior o igual al check-in."
            )
        return attrs

    def create(self, validated_data):
        turno = validated_data.pop("turno")
        capitan = validated_data.pop("capitan")
        try:
            return Lobby.crear(turno, capitan, **validated_data)
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        except ValueError as e:
            raise serializers.ValidationError(str(e))

    def update(self, instance, validated_data):
        validated_data.pop("turno", None)
        return super().update(instance, validated_data)
