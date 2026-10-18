from datetime import datetime, timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone

# Create your models here.
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

    # PROTECT: un club no puede quedar sin admin; se reasigna antes de borrar al usuario
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
        # limit_choices_to solo filtra formularios; acá se garantiza la regla
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

    # .con_club() evita una query por fila al renderizar __str__
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
        """Crea muchos turnos de una (ej: toda la semana de un club).

        Es la única vía para crear turnos en lote: calcula inicio/fin, valida
        los campos y chequea solapes entre los nuevos y contra los existentes
        (una query por cancha). Si alguno falla no se crea ninguno.
        """
        turnos = list(turnos)
        por_cancha = {}
        for turno in turnos:
            if not (turno.cancha_id and turno.fecha and turno.hora_inicio and turno.duracion):
                raise ValidationError("Cada turno necesita cancha, fecha, hora_inicio y duracion.")
            turno._calcular_horarios()
            turno.clean_fields(exclude=["inicio", "fin"])
            por_cancha.setdefault(turno.cancha_id, []).append(turno)

        with transaction.atomic():
            # bloquea las canchas para que otro proceso no inserte solapes entre
            # el chequeo y el bulk_create (no-op en SQLite, que serializa escrituras)
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
                            f"{anterior.inicio:%d/%m %H:%M} y {actual.inicio:%d/%m %H:%M}."
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
                                f"El turno {turno.inicio:%d/%m %H:%M} de la cancha "
                                f"{cancha_id} se solapa con uno existente."
                            )
            return self.bulk_create(turnos)

    # update()/bulk_update() no pasan por save(): dejarían inicio/fin desfasados
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

    # PROTECT: una cancha con turnos (historial) se desactiva con activa=False
    cancha = models.ForeignKey(
        Cancha,
        on_delete=models.PROTECT,
        related_name="turnos",
    )

    # Derivados de fecha + hora_inicio + duracion (se calculan en save()).
    # Guardados para poder detectar solapes con una sola query indexada.
    inicio = models.DateTimeField(editable=False)
    fin = models.DateTimeField(editable=False)

    # .con_cancha() evita queries extra por fila al renderizar __str__
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
            # red de seguridad a nivel base: el solape general se valida en
            # save()/crear_masivo(), pero este caso lo garantiza la base
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
        # Un save(update_fields=["estado"]) no toca el horario: se omite el chequeo
        if update_fields is None or self.CAMPOS_HORARIO & set(update_fields):
            self._calcular_horarios()
            if update_fields is not None:
                update_fields = {*update_fields, "inicio", "fin"}
            # Sin exclusion constraints (SQLite): el chequeo y el insert van
            # juntos en una transaccion
            with transaction.atomic():
                # bloquea la cancha: serializa altas concurrentes en bases con
                # row locks (Postgres); en SQLite es no-op
                Cancha.objects.select_for_update().filter(pk=self.cancha_id).first()
                self._validar_solape()
                super().save(*args, update_fields=update_fields, **kwargs)
        else:
            super().save(*args, update_fields=update_fields, **kwargs)

    def __str__(self):
        return f"{self.cancha} {self.fecha} {self.hora_inicio} [{self.estado}]"
