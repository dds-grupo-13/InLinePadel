from datetime import date, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from clubes.models import Cancha, Club, Turno, Zona
from config.test_utils import BaseAPITestCase
from usuarios.models import Usuario


class ClubTests(BaseAPITestCase):
    def test_str(self):
        self.assertEqual(str(self.club), "Club A")
        self.assertEqual(str(self.zona), "Tigre")

    def test_estado_inicial_activo(self):
        self.assertEqual(self.club.estado, Club.Estado.ACTIVO)

    def test_clean_rechaza_admin_sin_staff(self):
        comun = Usuario.objects.create_user("comun", "comun@x.com", "clave12345")
        club = Club(denominacion="Club C", direccion="Calle 3", zona=self.zona, admin=comun)
        with self.assertRaises(ValidationError) as ctx:
            club.clean()
        self.assertIn("admin", ctx.exception.message_dict)

    def test_clean_acepta_admin_staff(self):
        club = Club(denominacion="Club C", direccion="Calle 3", zona=self.zona, admin=self.admin)
        club.clean()

    def test_denominacion_unica_por_zona(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Club.objects.create(
                denominacion="Club A", direccion="Otra", zona=self.zona, admin=self.otro_admin
            )

    def test_misma_denominacion_en_otra_zona(self):
        otra_zona = Zona.objects.create(nombre="Pacheco")
        Club.objects.create(
            denominacion="Club A", direccion="Otra", zona=otra_zona, admin=self.otro_admin
        )


class CanchaTests(BaseAPITestCase):
    def test_str(self):
        self.assertEqual(str(self.cancha), "Cancha 1 - Club A")

    def test_valores_por_defecto(self):
        self.assertTrue(self.cancha.activa)
        self.assertEqual(self.cancha.tipo, Cancha.Tipo.TECHADA)

    def test_numero_cero_es_invalido(self):
        cancha = Cancha(numero=0, club=self.club)
        with self.assertRaises(ValidationError) as ctx:
            cancha.full_clean()
        self.assertIn("numero", ctx.exception.message_dict)

    def test_numero_unico_por_club(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Cancha.objects.create(numero=1, club=self.club)

    def test_con_club_evita_queries_extra(self):
        with self.assertNumQueries(1):
            canchas = list(Cancha.objects.con_club())
            [str(c) for c in canchas]


class TurnoCalculoTests(BaseAPITestCase):
    def test_save_calcula_inicio_y_fin(self):
        turno = Turno.objects.create(
            cancha=self.cancha, fecha=date(2030, 1, 10), hora_inicio=time(18, 30), precio=1000
        )
        self.assertEqual(timezone.localtime(turno.inicio).time(), time(18, 30))
        self.assertEqual(turno.fin - turno.inicio, timedelta(minutes=90))

    def test_duracion_personalizada(self):
        turno = Turno.objects.create(
            cancha=self.cancha,
            fecha=date(2030, 1, 10),
            hora_inicio=time(10),
            duracion=60,
            precio=1000,
        )
        self.assertEqual(turno.fin - turno.inicio, timedelta(minutes=60))

    def test_estado_inicial_libre(self):
        self.assertEqual(self.turno(self.cancha).estado, Turno.Estado.LIBRE)

    def test_str(self):
        turno = self.turno(self.cancha)
        self.assertIn("Cancha 1 - Club A", str(turno))
        self.assertIn("[LIBRE]", str(turno))

    def test_cambiar_horario_recalcula_inicio_y_fin(self):
        turno = self.turno(self.cancha, hora=20)
        turno.hora_inicio = time(9)
        turno.save()
        turno.refresh_from_db()
        self.assertEqual(timezone.localtime(turno.inicio).time(), time(9))
        self.assertEqual(turno.fin - turno.inicio, timedelta(minutes=90))

    def test_save_con_update_fields_de_horario_incluye_inicio_y_fin(self):
        turno = self.turno(self.cancha, hora=20)
        turno.duracion = 120
        turno.save(update_fields=["duracion"])
        turno.refresh_from_db()
        self.assertEqual(turno.fin - turno.inicio, timedelta(minutes=120))

    def test_save_de_estado_no_valida_solape(self):
        turno = self.turno(self.cancha)
        with self.assertNumQueries(1):
            turno.estado = Turno.Estado.NO_DISPONIBLE
            turno.save(update_fields=["estado"])
        turno.refresh_from_db()
        self.assertEqual(turno.estado, Turno.Estado.NO_DISPONIBLE)


class TurnoValidacionTests(BaseAPITestCase):
    def test_solape_parcial_en_la_misma_cancha(self):
        self.turno(self.cancha, hora=20)
        solapado = Turno(
            cancha=self.cancha,
            fecha=(timezone.localtime() + timedelta(days=3)).date(),
            hora_inicio=time(21),
            precio=Decimal("1000"),
        )
        with self.assertRaises(ValidationError):
            solapado.save()

    def test_turno_contiguo_no_se_solapa(self):
        self.turno(self.cancha, hora=20)
        fecha = (timezone.localtime() + timedelta(days=3)).date()
        Turno.objects.create(
            cancha=self.cancha, fecha=fecha, hora_inicio=time(21, 30), precio=1000
        )

    def test_mismo_horario_en_otra_cancha(self):
        self.turno(self.cancha, hora=20)
        self.turno(self.otra_cancha, hora=20)

    def test_clean_detecta_solape(self):
        existente = self.turno(self.cancha, hora=20)
        nuevo = Turno(
            cancha=self.cancha, fecha=existente.fecha, hora_inicio=time(20, 30), precio=1000
        )
        with self.assertRaises(ValidationError):
            nuevo.clean()

    def test_clean_no_se_solapa_consigo_mismo(self):
        turno = self.turno(self.cancha, hora=20)
        turno.clean()

    def test_clean_con_campos_incompletos_no_falla(self):
        Turno(precio=1000).clean()

    def test_precio_negativo_es_invalido(self):
        turno = Turno(
            cancha=self.cancha, fecha=date(2030, 1, 1), hora_inicio=time(10), precio=-1
        )
        with self.assertRaises(ValidationError) as ctx:
            turno.full_clean(exclude=["inicio", "fin"])
        self.assertIn("precio", ctx.exception.message_dict)

    def test_duracion_cero_es_invalida(self):
        turno = Turno(
            cancha=self.cancha,
            fecha=date(2030, 1, 1),
            hora_inicio=time(10),
            duracion=0,
            precio=1000,
        )
        with self.assertRaises(ValidationError) as ctx:
            turno.full_clean(exclude=["inicio", "fin"])
        self.assertIn("duracion", ctx.exception.message_dict)


class TurnoQuerySetTests(BaseAPITestCase):
    def nuevo(self, hora, minutos=0, cancha=None, fecha=None, duracion=90):
        return Turno(
            cancha=cancha or self.cancha,
            fecha=fecha or date(2030, 5, 1),
            hora_inicio=time(hora, minutos),
            duracion=duracion,
            precio=Decimal("2500"),
        )

    def test_crear_masivo_crea_todos_con_horarios(self):
        creados = Turno.objects.crear_masivo([self.nuevo(9), self.nuevo(11), self.nuevo(13)])
        self.assertEqual(len(creados), 3)
        self.assertEqual(Turno.objects.filter(cancha=self.cancha).count(), 3)
        self.assertTrue(all(t.inicio and t.fin for t in creados))

    def test_crear_masivo_acepta_varias_canchas(self):
        Turno.objects.crear_masivo(
            [self.nuevo(9), self.nuevo(9, cancha=self.otra_cancha)]
        )
        self.assertEqual(Turno.objects.count(), 2)

    def test_crear_masivo_rechaza_solape_entre_nuevos_y_no_crea_ninguno(self):
        with self.assertRaises(ValidationError):
            Turno.objects.crear_masivo([self.nuevo(9), self.nuevo(10), self.nuevo(15)])
        self.assertFalse(Turno.objects.exists())

    def test_crear_masivo_rechaza_solape_con_existente(self):
        Turno.objects.create(
            cancha=self.cancha, fecha=date(2030, 5, 1), hora_inicio=time(10), precio=1000
        )
        with self.assertRaises(ValidationError):
            Turno.objects.crear_masivo([self.nuevo(8), self.nuevo(11)])
        self.assertEqual(Turno.objects.count(), 1)

    def test_crear_masivo_exige_campos_obligatorios(self):
        faltante = Turno(cancha=self.cancha, fecha=date(2030, 5, 1), precio=1000)
        with self.assertRaises(ValidationError):
            Turno.objects.crear_masivo([faltante])

    def test_crear_masivo_valida_los_campos(self):
        invalido = self.nuevo(9)
        invalido.precio = Decimal("-5")
        with self.assertRaises(ValidationError):
            Turno.objects.crear_masivo([invalido])

    def test_crear_masivo_vacio(self):
        self.assertEqual(Turno.objects.crear_masivo([]), [])

    def test_update_masivo_de_horario_esta_prohibido(self):
        self.turno(self.cancha)
        for campo in ("fecha", "hora_inicio", "duracion", "cancha"):
            with self.subTest(campo=campo), self.assertRaises(ValueError):
                Turno.objects.update(**{campo: None})

    def test_update_masivo_de_estado_esta_permitido(self):
        self.turno(self.cancha)
        actualizados = Turno.objects.update(estado=Turno.Estado.NO_DISPONIBLE)
        self.assertEqual(actualizados, 1)

    def test_bulk_update_de_horario_esta_prohibido(self):
        turno = self.turno(self.cancha)
        with self.assertRaises(ValueError):
            Turno.objects.bulk_update([turno], ["hora_inicio"])

    def test_bulk_update_de_estado_esta_permitido(self):
        turno = self.turno(self.cancha)
        turno.estado = Turno.Estado.CUMPLIDO
        Turno.objects.bulk_update([turno], ["estado"])
        turno.refresh_from_db()
        self.assertEqual(turno.estado, Turno.Estado.CUMPLIDO)

    def test_con_cancha_evita_queries_extra(self):
        self.turno(self.cancha)
        with self.assertNumQueries(1):
            [str(t) for t in Turno.objects.con_cancha()]
