from django.db import transaction
from rest_framework import serializers

from .models import Jugador, Usuario


class UsuarioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Usuario
        fields = ["id", "username", "email", "first_name", "last_name", "password"]
        extra_kwargs = {"password": {"write_only": True, "min_length": 8}}

    def create(self, validated_data):
        return Usuario.objects.create_user(**validated_data)

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=["password"])
        return instance


class JugadorSerializer(serializers.ModelSerializer):
    usuario = UsuarioSerializer(read_only=True)

    class Meta:
        model = Jugador
        fields = ["usuario", "posicion", "zona"]


class JugadorPublicoSerializer(serializers.ModelSerializer):
    """Datos mínimos de un jugador para terceros (buscador, inscriptos)."""

    id = serializers.IntegerField(source="pk", read_only=True)
    username = serializers.CharField(source="usuario.username", read_only=True)
    nombre = serializers.SerializerMethodField()

    class Meta:
        model = Jugador
        fields = ["id", "username", "nombre", "posicion", "zona"]

    def get_nombre(self, obj):
        return obj.usuario.get_full_name() or obj.usuario.username


class RegistroJugadorSerializer(serializers.ModelSerializer):
    """Alta de jugador: crea el Usuario y su perfil en una transacción."""

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
            UsuarioSerializer(partial=True).update(instance.usuario, datos)
        return super().update(instance, validated_data)


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)
