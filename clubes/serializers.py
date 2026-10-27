from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from usuarios.models import Usuario
from usuarios.serializers import validar_password

from .models import Cancha, Club, Turno, Zona


class ZonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zona
        fields = ["id", "nombre"]


class ClubSerializer(serializers.ModelSerializer):
    admin_username = serializers.CharField(write_only=True, required=False)
    admin_email = serializers.EmailField(write_only=True, required=False)
    admin_password = serializers.CharField(write_only=True, required=False, min_length=8)

    class Meta:
        model = Club
        fields = [
            "id", "denominacion", "direccion", "estado", "zona", "admin",
            "admin_username", "admin_email", "admin_password",
        ]
        read_only_fields = ["estado"]
        extra_kwargs = {"admin": {"required": False}}

    def validate_admin_username(self, valor):
        if Usuario.objects.filter(username=valor).exists():
            raise serializers.ValidationError("Ya existe un usuario con ese nombre.")
        return valor

    def validate_admin_email(self, valor):
        if Usuario.objects.filter(email__iexact=valor).exists():
            raise serializers.ValidationError("Ya existe un/a usuario con este/a email.")
        return valor

    def validate_admin(self, admin):
        if not admin.is_staff:
            raise serializers.ValidationError("El admin del club debe ser staff.")
        return admin

    def validate(self, attrs):
        attrs = super().validate(attrs)
        credenciales = ("admin_username", "admin_email", "admin_password")
        if self.instance is None:
            if "admin" in attrs:
                if any(c in attrs for c in credenciales):
                    raise serializers.ValidationError(
                        "Indicá un admin existente o las credenciales de uno nuevo, no ambos."
                    )
            elif not all(c in attrs for c in credenciales):
                raise serializers.ValidationError(
                    "Indicá el admin del club o sus credenciales (usuario, email y contraseña)."
                )
            else:
                candidato = Usuario(
                    username=attrs["admin_username"], email=attrs["admin_email"]
                )
                try:
                    validar_password(attrs["admin_password"], candidato)
                except serializers.ValidationError as e:
                    raise serializers.ValidationError({"admin_password": e.detail})
        return attrs

    def to_representation(self, club):
        datos = super().to_representation(club)
        request = self.context.get("request")
        if request is None or not request.user.is_staff:
            datos.pop("admin", None)
        return datos

    @transaction.atomic
    def create(self, validated_data):
        datos = {c: validated_data.pop(c, None) for c in (
            "admin_username", "admin_email", "admin_password")}
        if "admin" not in validated_data:
            validated_data["admin"] = Usuario.objects.create_user(
                username=datos["admin_username"],
                email=datos["admin_email"],
                password=datos["admin_password"],
                is_staff=True,
            )
        return super().create(validated_data)

    def update(self, instance, validated_data):
        for c in ("admin_username", "admin_email", "admin_password"):
            validated_data.pop(c, None)
        return super().update(instance, validated_data)


def _validar_club_propio(request, club):
    user = request.user
    if not user.is_superuser and club.admin_id != user.pk:
        raise serializers.ValidationError("Solo podés operar sobre tu propio club.")
    return club


class CanchaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cancha
        fields = ["id", "numero", "activa", "tipo", "club"]

    def validate_club(self, club):
        return _validar_club_propio(self.context["request"], club)


class TurnoSerializer(serializers.ModelSerializer):
    club = serializers.IntegerField(source="cancha.club_id", read_only=True)
    club_nombre = serializers.CharField(source="cancha.club.denominacion", read_only=True)
    cancha_numero = serializers.IntegerField(source="cancha.numero", read_only=True)
    cancha_tipo = serializers.CharField(source="cancha.tipo", read_only=True)
    cierre = serializers.SerializerMethodField()
    liberable = serializers.BooleanField(read_only=True, default=False)

    class Meta:
        model = Turno
        fields = [
            "id", "fecha", "hora_inicio", "duracion", "precio",
            "estado", "cancha", "inicio", "fin", "cierre",
            "club", "club_nombre", "cancha_numero", "cancha_tipo", "liberable",
        ]
        read_only_fields = ["inicio", "fin", "estado"]

    def to_representation(self, turno):
        datos = super().to_representation(turno)
        request = self.context.get("request")
        es_staff = getattr(getattr(request, "user", None), "is_staff", False)
        if datos.get("liberable") and not es_staff:
            datos["estado"] = Turno.Estado.LIBRE.value
        return datos

    def get_cierre(self, turno):
        from partidas.models import Lobby

        return serializers.DateTimeField().to_representation(Lobby.cierre_de(turno))

    def validate_cancha(self, cancha):
        _validar_club_propio(self.context["request"], cancha.club)
        return cancha

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


class CancelacionClubSerializer(serializers.Serializer):
    motivo = serializers.CharField(min_length=5, max_length=200)


class TurnoOcupacionSerializer(serializers.ModelSerializer):
    cancha_numero = serializers.IntegerField(source="cancha.numero", read_only=True)
    lobby = serializers.SerializerMethodField()

    class Meta:
        model = Turno
        fields = [
            "id", "fecha", "hora_inicio", "inicio", "fin", "cancha", "cancha_numero",
            "estado", "lobby",
        ]
        read_only_fields = ["inicio", "fin"]

    def get_lobby(self, turno):
        lobby = next((l for l in turno.lobbies.all() if l.estado != "CANCELADO"), None)
        if lobby is None:
            return None
        return {
            "id": lobby.pk,
            "estado": lobby.estado,
            "vencido": lobby.esta_vencido(),
            "privacidad": lobby.privacidad,
            "cupos_ocupados": len(lobby.inscripciones.all()),
            "reserva": lobby.estado_reserva,
            "codigo_reserva": lobby.codigo_reserva,
        }
