from django.db import models

class Resultado(models.Model):

    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        EN_DISPUTA = "EN_DISPUTA", "En disputa"

    partido = models.OneToOneField(
        "partidas.Partido",
        on_delete=models.CASCADE,
        related_name="resultado",
    )
    fecha_carga = models.DateTimeField(auto_now_add=True)
    estado = models.CharField(
        max_length=10,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
    )

    class Meta:
        verbose_name = "Resultado"
        verbose_name_plural = "Resultados"

    def __str__(self):
        return f"Resultado del Partido #{self.partido_id} [{self.estado}]"


class Pareja(models.Model):

    resultado = models.ForeignKey(
        Resultado,
        on_delete=models.CASCADE,
        related_name="parejas",
    )

    jugadores = models.ManyToManyField(
        "usuarios.Jugador",
        related_name="parejas",
    )
    numero_pareja = models.PositiveSmallIntegerField()
    ganadora = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Pareja"
        verbose_name_plural = "Parejas"
        constraints = [
            models.UniqueConstraint(
                fields=["resultado", "numero_pareja"],
                name="numero_pareja_unico_por_resultado",
            ),
        ]

    def __str__(self):
        return f"Pareja {self.numero_pareja} (Resultado #{self.resultado_id})"


class HistorialPuntaje(models.Model):

    jugador = models.ForeignKey(
        "usuarios.Jugador",
        on_delete=models.CASCADE,
        related_name="historial_puntaje",
    )

    partido = models.ForeignKey(
        "partidas.Partido",
        on_delete=models.SET_NULL,
        related_name="cambios_puntaje",
        blank=True,
        null=True,
    )
    puntaje_anterior = models.IntegerField()
    puntaje_nuevo = models.IntegerField()
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Historial de puntaje"
        verbose_name_plural = "Historiales de puntaje"
        ordering = ["-fecha"]

    def __str__(self):
        return f"{self.jugador}: {self.puntaje_anterior} → {self.puntaje_nuevo}"
