from django.contrib.auth import password_validation, update_session_auth_hash
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from .models import Jugador, Usuario


def validar_password(password, usuario=None):
    try:
        password_validation.validate_password(password, usuario)
    except DjangoValidationError as e:
        raise serializers.ValidationError(list(e.messages))


class UsuarioSerializer(serializers.ModelSerializer):
    password_actual = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Usuario
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "password", "password_actual",
        ]
        extra_kwargs = {
            "password": {"write_only": True, "min_length": 8},
            "username": {"validators": [UnicodeUsernameValidator()]},
            "email": {"validators": []},
        }

    def _actual(self):
        if self.instance is not None:
            return self.instance
        return getattr(getattr(self.parent, "instance", None), "usuario", None)

    def _validar_unico(self, campo, valor, mensaje, lookup="exact"):
        existentes = Usuario.objects.filter(**{f"{campo}__{lookup}": valor})
        actual = self._actual()
        if actual is not None:
            existentes = existentes.exclude(pk=actual.pk)
        if existentes.exists():
            raise serializers.ValidationError(mensaje)
        return valor

    def validate_username(self, valor):
        return self._validar_unico("username", valor, "Ya existe un usuario con ese nombre.")

    def validate_email(self, valor):
        return self._validar_unico(
            "email", valor, "Ya existe un/a usuario con este/a email.", lookup="iexact"
        )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        actual = self._actual()
        password = attrs.get("password")
        if password is None:
            return attrs
        if actual is not None:
            if not actual.check_password(attrs.get("password_actual", "")):
                raise serializers.ValidationError(
                    {"password_actual": "Ingresá tu contraseña actual para cambiarla."}
                )
        candidato = actual or Usuario(
            **{c: attrs[c] for c in ("username", "email", "first_name", "last_name") if c in attrs}
        )
        try:
            validar_password(password, candidato)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"password": e.detail})
        return attrs

    def create(self, validated_data):
        validated_data.pop("password_actual", None)
        return Usuario.objects.create_user(**validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("password_actual", None)
        password = validated_data.pop("password", None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=["password"])
            request = self.context.get("request")
            if request is not None and request.user.pk == instance.pk:
                update_session_auth_hash(request, instance)
        return instance


class JugadorSerializer(serializers.ModelSerializer):
    usuario = UsuarioSerializer(read_only=True)

    class Meta:
        model = Jugador
        fields = ["usuario", "posicion", "zona"]


class JugadorPublicoSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(source="pk", read_only=True)
    username = serializers.CharField(source="usuario.username", read_only=True)
    nombre = serializers.SerializerMethodField()

    class Meta:
        model = Jugador
        fields = ["id", "username", "nombre", "posicion", "zona"]

    def get_nombre(self, obj):
        return obj.usuario.get_full_name() or obj.usuario.username


class RegistroJugadorSerializer(serializers.ModelSerializer):
    usuario = UsuarioSerializer()

    class Meta:
        model = Jugador
        fields = ["usuario", "posicion", "zona"]

    @transaction.atomic
    def create(self, validated_data):
        datos = validated_data.pop("usuario")
        usuario = UsuarioSerializer().create(datos)
        return Jugador.objects.create(usuario=usuario, **validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        datos = validated_data.pop("usuario", None)
        if datos:
            UsuarioSerializer(partial=True, context=self.context).update(instance.usuario, datos)
        return super().update(instance, validated_data)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
