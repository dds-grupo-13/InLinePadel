from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Contacto, Invitacion, Notificacion, SolicitudAcceso


class NotificacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notificacion
        fields = ["id", "mensaje", "leida", "fecha", "usuario"]
        read_only_fields = ["mensaje", "fecha", "usuario"]


class _PedidoLobbySerializer(serializers.ModelSerializer):
    def create(self, validated_data):
        try:
            return super().create(validated_data)
        except DjangoValidationError as e:
            raise serializers.ValidationError(
                e.message_dict if hasattr(e, "error_dict") else e.messages
            )


class ContactoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contacto
        fields = ["id", "jugador", "contacto", "estado", "fecha"]
        read_only_fields = ["jugador", "estado", "fecha"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        jugador = attrs.get("jugador") or getattr(self.instance, "jugador", None)
        contacto = attrs.get("contacto") or getattr(self.instance, "contacto", None)
        if jugador and contacto and jugador == contacto:
            raise serializers.ValidationError("No podés agregarte a vos mismo.")
        return attrs


class SolicitudAccesoSerializer(_PedidoLobbySerializer):
    class Meta:
        model = SolicitudAcceso
        fields = ["id", "lobby", "jugador", "estado", "fecha"]
        read_only_fields = ["jugador", "estado", "fecha"]


class InvitacionSerializer(_PedidoLobbySerializer):
    class Meta:
        model = Invitacion
        fields = ["id", "lobby", "emisor", "receptor", "estado", "fecha"]
        read_only_fields = ["emisor", "estado", "fecha"]
