from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import Cancha, Club, Turno, Zona


class ZonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zona
        fields = ["id", "nombre"]


class ClubSerializer(serializers.ModelSerializer):
    class Meta:
        model = Club
        fields = ["id", "denominacion", "direccion", "estado", "zona", "admin"]

    def validate_admin(self, admin):
        if not admin.is_staff:
            raise serializers.ValidationError("El admin del club debe ser staff.")
        return admin


class CanchaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cancha
        fields = ["id", "numero", "activa", "tipo", "club"]


class TurnoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Turno
        fields = [
            "id", "fecha", "hora_inicio", "duracion", "precio",
            "estado", "cancha", "inicio", "fin",
        ]
        read_only_fields = ["inicio", "fin", "estado"]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        campos = {
            nombre: attrs.get(nombre, getattr(self.instance, nombre, None))
            for nombre in ("cancha", "fecha", "hora_inicio", "duracion")
        }
        turno = Turno(pk=getattr(self.instance, "pk", None), **campos)
        try:
            turno.clean()
        except DjangoValidationError as e:
            raise serializers.ValidationError(e.messages)
        return attrs
