from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone


class UsuarioManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("El usuario debe tener un email.")
        email = self.normalize_email(email)
        usuario = self.model(email=email, **extra_fields)

        usuario.set_password(password)
        usuario.save(using=self._db)
        return usuario

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class Usuario(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    fecha_alta = models.DateTimeField(auto_now_add=True)

    objects = UsuarioManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        verbose_name = "Usuario"
        verbose_name_plural = "Usuarios"

    def __str__(self):
        return self.email


class AdminSistema(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="admin_sistema",
    )

    class Meta:
        verbose_name = "Administrador del sistema"
        verbose_name_plural = "Administradores del sistema"

    def __str__(self):
        return f"AdminSistema <{self.usuario.email}>"


class AdminClub(models.Model):
    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="admin_club",
    )
    club = models.ForeignKey(
        "clubes.Club",
        on_delete=models.CASCADE,
        related_name="administradores",
    )

    class Meta:
        verbose_name = "Administrador de club"
        verbose_name_plural = "Administradores de club"

    def __str__(self):
        return f"AdminClub <{self.usuario.email}>"


class Jugador(models.Model):
    class Posicion(models.TextChoices):
        REVES = "REVES", "Revés"
        DRIVE = "DRIVE", "Drive"
        INDISTINTO = "INDISTINTO", "Indistinto"

    usuario = models.OneToOneField(
        Usuario,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="jugador",
    )
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100)
    posicion_preferida = models.CharField(
        max_length=10,
        choices=Posicion.choices,
        default=Posicion.INDISTINTO,
    )
    zona = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Jugador"
        verbose_name_plural = "Jugadores"

    def __str__(self):
        return f"{self.nombre} {self.apellido}"

    def categoria_visible(self) -> str:
        raise NotImplementedError(
            "El sistema de niveles (Elo) no está implementado en esta versión. "
            "La categoría visible quedó fuera de alcance."
        )
