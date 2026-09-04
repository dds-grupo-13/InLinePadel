from datetime import datetime

from django.db import models
from django.utils import timezone


class Club(models.Model):

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        SUSPENDIDO = "SUSPENDIDO", "Suspendido"
        BAJA = "BAJA", "Dado de baja"

    denominacion = models.CharField(max_length=150)
    direccion = models.CharField(max_length=200)
    zona = models.CharField(max_length=100)
    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.ACTIVO,
    )

    habilitado_por = models.ForeignKey(
        "usuarios.AdminSistema",
        on_delete=models.PROTECT,
        related_name="clubes_habilitados",
    )

    class Meta:
        verbose_name = "Club"
        verbose_name_plural = "Clubes"

    def __str__(self):
        return self.denominacion


class Cancha(models.Model):

    class Tipo(models.TextChoices):
        TECHADA = "TECHADA", "Techada"
        DESCUBIERTA = "DESCUBIERTA", "Descubierta"

    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name="canchas",
    )
    identificacion = models.CharField(max_length=50)
    tipo = models.CharField(max_length=12, choices=Tipo.choices)

    class Meta:
        verbose_name = "Cancha"
        verbose_name_plural = "Canchas"

    def __str__(self):
        return f"{self.identificacion} - {self.club.denominacion}"


class Turno(models.Model):

    class Estado(models.TextChoices):
        LIBRE = "LIBRE", "Libre"
        BLOQUEADO = "BLOQUEADO", "Bloqueado"
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        NO_DISPONIBLE = "NO_DISPONIBLE", "No disponible"
        CUMPLIDO = "CUMPLIDO", "Cumplido"

    cancha = models.ForeignKey(
        Cancha,
        on_delete=models.CASCADE,
        related_name="turnos",
    )
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    duracion = models.PositiveIntegerField(default=90)
    precio = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(
        max_length=14,
        choices=Estado.choices,
        default=Estado.LIBRE,
    )

    class Meta:
        verbose_name = "Turno"
        verbose_name_plural = "Turnos"

        constraints = [
            models.UniqueConstraint(
                fields=["cancha", "fecha", "hora_inicio"],
                name="turno_unico_por_cancha_y_horario",
            )
        ]

    def __str__(self):
        return f"{self.cancha} {self.fecha} {self.hora_inicio} [{self.estado}]"

    def esta_disponible_para_reserva(self):
        if self.estado != self.Estado.LIBRE:
            return False

        ahora = timezone.now()
        turno_dt = datetime.combine(self.fecha, self.hora_inicio)
        turno_aware = timezone.make_aware(turno_dt, timezone.get_current_timezone())
        return turno_aware > ahora
