from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models

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

    PUNTAJE_INICIAL = 1000
    PARTIDOS_PARA_CONSOLIDAR = 10

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
    puntaje = models.IntegerField(default=PUNTAJE_INICIAL)
    partidos_registrados = models.IntegerField(default=0)

    class Meta:
        verbose_name = "Jugador"
        verbose_name_plural = "Jugadores"

    def __str__(self):
        return f"{self.nombre} {self.apellido} ({self.puntaje})"

    def es_provisorio(self) -> bool:
        return self.partidos_registrados < self.PARTIDOS_PARA_CONSOLIDAR

    def factor_k(self) -> int:
        return 40 if self.es_provisorio() else 20

    def categoria_visible(self) -> str:
        p = self.puntaje
        if p < 850:
            return "8va"
        if p < 1000:
            return "7ma"
        if p < 1150:
            return "6ta"
        if p < 1300:
            return "5ta"
        if p < 1450:
            return "4ta"
        if p < 1600:
            return "3ra"
        if p < 1750:
            return "2da"
        return "1ra"
