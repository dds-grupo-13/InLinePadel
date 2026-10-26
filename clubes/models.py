from datetime import datetime, timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

class Zona(models.Model):
    nombre = models.CharField(max_length=100)

    class Meta:
        verbose_name = "Zona"
        verbose_name_plural = "Zonas"

    def __str__(self):
        return self.nombre


class Club(models.Model):
    denominacion = models.CharField(max_length=100)
    direccion = models.CharField(max_length=200)

    class Estado(models.TextChoices):
        ACTIVO = "ACTIVO", "Activo"
        SUSPENDIDO = "SUSPENDIDO", "Suspendido"
        BAJA = "BAJA", "Dado de baja"

    estado = models.CharField(
        max_length=12,
        choices=Estado.choices,
        default=Estado.ACTIVO,
    )

    zona = models.ForeignKey(
        Zona,
        on_delete=models.PROTECT,
        related_name="clubes",
    )

    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="clubes_administrados",
        limit_choices_to={"is_staff": True},
    )

    class Meta:
        verbose_name = "Club"
        verbose_name_plural = "Clubes"

        constraints = [
            models.UniqueConstraint(
                fields=["zona", "denominacion"],
                name="club_unico_por_zona_y_denominacion",
            )
        ]

    def clean(self):
        super().clean()
        if self.admin_id and not self.admin.is_staff:
            raise ValidationError({"admin": "El admin del club debe ser staff."})

    def __str__(self):
        return self.denominacion


class CanchaQuerySet(models.QuerySet):
    def con_club(self):
        return self.select_related("club")


class Cancha(models.Model):
    numero = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    activa = models.BooleanField(default=True)

    class Tipo(models.TextChoices):
        TECHADA = "TECHADA", "Techada"
        DESCUBIERTA = "DESCUBIERTA", "Descubierta"

    tipo = models.CharField(
        max_length=12,
        choices=Tipo.choices,
        default=Tipo.TECHADA
    )

    club = models.ForeignKey(
        Club,
        on_delete=models.CASCADE,
        related_name="canchas",
    )

    objects = CanchaQuerySet.as_manager()

    class Meta:
        verbose_name = "Cancha"
        verbose_name_plural = "Canchas"

        constraints = [
            models.UniqueConstraint(
                fields=["club", "numero"],
                name="cancha_unica_por_club_y_numero",
            )
        ]

    def __str__(self):
        return f"Cancha {self.numero} - {self.club.denominacion}"


class TurnoQuerySet(models.QuerySet):
    def con_cancha(self):
        return self.select_related("cancha", "cancha__club")

    def crear_masivo(self, turnos):
        turnos = list(turnos)
        por_cancha = {}
        for turno in turnos:
            if not (turno.cancha_id and turno.fecha and turno.hora_inicio and turno.duracion):
                raise ValidationError("Cada turno necesita cancha, fecha, hora_inicio y duracion.")
            turno._calcular_horarios()
            turno.clean_fields(exclude=["inicio", "fin"])
            por_cancha.setdefault(turno.cancha_id, []).append(turno)

        with transaction.atomic():
            list(
                Cancha.objects.select_for_update()
                .filter(pk__in=por_cancha)
                .values_list("pk", flat=True)
            )
            for cancha_id, nuevos in por_cancha.items():
                nuevos.sort(key=lambda t: t.inicio)
                for anterior, actual in zip(nuevos, nuevos[1:]):
                    if actual.inicio < anterior.fin:
                        raise ValidationError(
                            f"Dos turnos nuevos se solapan en la cancha {cancha_id}: "
                            f"{timezone.localtime(anterior.inicio):%d/%m %H:%M} y "
                            f"{timezone.localtime(actual.inicio):%d/%m %H:%M}."
                        )
                existentes = self.model.objects.filter(
                    cancha_id=cancha_id,
                    inicio__lt=nuevos[-1].fin,
                    fin__gt=nuevos[0].inicio,
                ).values_list("inicio", "fin")
                for ini, fin in existentes:
                    for turno in nuevos:
                        if turno.inicio < fin and ini < turno.fin:
                            raise ValidationError(
                                f"El turno {timezone.localtime(turno.inicio):%d/%m %H:%M} de la cancha "
                                f"{cancha_id} se solapa con uno existente."
                            )
            return self.bulk_create(turnos)

    def update(self, **kwargs):
        self._rechazar_campos_horario(kwargs)
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, *args, **kwargs):
        self._rechazar_campos_horario(fields)
        return super().bulk_update(objs, fields, *args, **kwargs)

    def _rechazar_campos_horario(self, campos):
        if self.model.CAMPOS_HORARIO & set(campos):
            raise ValueError(
                "Cambiar cancha, fecha, hora_inicio o duracion requiere save() "
                "para recalcular inicio/fin y validar solapes."
            )


class Turno(models.Model):
    fecha = models.DateField()
    hora_inicio = models.TimeField()
    duracion = models.PositiveIntegerField(
        default=90,
        validators=[MinValueValidator(1)],
    )
    precio = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(0)],
    )

    class Estado(models.TextChoices):
        LIBRE = "LIBRE", "Libre"
        BLOQUEADO = "BLOQUEADO", "Bloqueado"
        CONFIRMADO = "CONFIRMADO", "Confirmado"
        NO_DISPONIBLE = "NO_DISPONIBLE", "No disponible"
        CUMPLIDO = "CUMPLIDO", "Cumplido"

    estado = models.CharField(
        max_length=14,
        choices=Estado.choices,
        default=Estado.LIBRE
    )

    cancha = models.ForeignKey(
        Cancha,
        on_delete=models.PROTECT,
        related_name="turnos",
    )

    inicio = models.DateTimeField(editable=False)
    fin = models.DateTimeField(editable=False)

    objects = TurnoQuerySet.as_manager()

    class Meta:
        verbose_name = "Turno"
        verbose_name_plural = "Turnos"
        ordering = ["inicio"]

        indexes = [
            models.Index(fields=["cancha", "inicio"], name="turno_cancha_inicio_idx"),
            models.Index(fields=["fecha", "estado"], name="turno_fecha_estado_idx"),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["cancha", "fecha", "hora_inicio"],
                name="turno_unico_por_cancha_y_horario",
            ),
            models.CheckConstraint(
                condition=models.Q(duracion__gt=0),
                name="turno_duracion_positiva",
            ),
            models.CheckConstraint(
                condition=models.Q(fin__gt=models.F("inicio")),
                name="turno_fin_posterior_a_inicio",
            ),
            models.CheckConstraint(
                condition=models.Q(precio__gte=0),
                name="turno_precio_no_negativo",
            ),
        ]

    CAMPOS_HORARIO = {"cancha", "cancha_id", "fecha", "hora_inicio", "duracion"}

    def _calcular_horarios(self):
        self.inicio = timezone.make_aware(datetime.combine(self.fecha, self.hora_inicio))
        self.fin = self.inicio + timedelta(minutes=self.duracion)

    def _validar_solape(self):
        solapa = Turno.objects.filter(
            cancha_id=self.cancha_id,
            inicio__lt=self.fin,
            fin__gt=self.inicio,
        ).exclude(pk=self.pk)
        if solapa.exists():
            raise ValidationError("El turno se solapa con otro de la misma cancha.")

    def clean(self):
        super().clean()
        if not (self.cancha_id and self.fecha and self.hora_inicio and self.duracion):
            return
        self._calcular_horarios()
        self._validar_solape()

    def save(self, *args, update_fields=None, **kwargs):
        if update_fields is None or self.CAMPOS_HORARIO & set(update_fields):
            self._calcular_horarios()
            if update_fields is not None:
                update_fields = {*update_fields, "inicio", "fin"}
            with transaction.atomic():
                Cancha.objects.select_for_update().filter(pk=self.cancha_id).first()
                self._validar_solape()
                super().save(*args, update_fields=update_fields, **kwargs)
        else:
            super().save(*args, update_fields=update_fields, **kwargs)

    def __str__(self):
        return f"{self.cancha} {self.fecha} {self.hora_inicio} [{self.estado}]"
