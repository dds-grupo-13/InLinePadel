from types import SimpleNamespace
from unittest import mock

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from django.test import SimpleTestCase, TestCase
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory

from config.exceptions import (
    Conflicto,
    ErrorDominio,
    _es_falla_de_bloqueo,
    manejador_excepciones,
)
from config.permissions import (
    EsAdminClub,
    EsAdminSistema,
    EsJugador,
    SoloLecturaOAdminSistema,
)
from social.models import Notificacion
from social.notificaciones import notificar
from usuarios.models import Jugador, Usuario


def _usuario(**atributos):
    base = {"is_authenticated": True, "is_staff": False, "is_superuser": False}
    base.update(atributos)
    return SimpleNamespace(**base)


def _request(metodo="get", user=None):
    request = getattr(APIRequestFactory(), metodo)("/")
    request.user = user
    return request


class JerarquiaDeErroresTests(SimpleTestCase):
    def test_conflicto_es_un_error_de_dominio(self):
        self.assertTrue(issubclass(Conflicto, ErrorDominio))

    def test_error_de_dominio_es_value_error(self):
        self.assertTrue(issubclass(ErrorDominio, ValueError))


class EsFallaDeBloqueoTests(SimpleTestCase):
    def _error(self, mensaje, sqlstate=None):
        exc = OperationalError(mensaje)
        if sqlstate is not None:
            causa = Exception()
            causa.sqlstate = sqlstate
            exc.__cause__ = causa
        return exc

    def test_sqlstates_de_bloqueo_de_postgres(self):
        for sqlstate in ("55P03", "40001", "40P01"):
            with self.subTest(sqlstate=sqlstate):
                self.assertTrue(_es_falla_de_bloqueo(self._error("x", sqlstate)))

    def test_otro_sqlstate_no_es_bloqueo(self):
        self.assertFalse(_es_falla_de_bloqueo(self._error("locked", "08006")))

    def test_sqlite_database_is_locked(self):
        self.assertTrue(_es_falla_de_bloqueo(self._error("database is locked")))

    def test_error_operacional_cualquiera_no_es_bloqueo(self):
        self.assertFalse(_es_falla_de_bloqueo(self._error("connection refused")))


class ManejadorDeExcepcionesTests(SimpleTestCase):
    def manejar(self, exc):
        return manejador_excepciones(exc, {})

    def test_conflicto_da_409(self):
        respuesta = self.manejar(Conflicto("ocupado"))
        self.assertEqual(respuesta.status_code, 409)
        self.assertEqual(respuesta.data, {"detail": "ocupado"})

    def test_error_de_dominio_da_400(self):
        respuesta = self.manejar(ErrorDominio("mal"))
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.data, {"detail": "mal"})

    def test_validation_error_con_campos_devuelve_el_diccionario(self):
        respuesta = self.manejar(DjangoValidationError({"campo": "invalido"}))
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.data, {"campo": ["invalido"]})

    def test_validation_error_sin_campos_devuelve_la_lista(self):
        respuesta = self.manejar(DjangoValidationError("general"))
        self.assertEqual(respuesta.status_code, 400)
        self.assertEqual(respuesta.data, ["general"])

    def test_falla_de_bloqueo_da_409(self):
        respuesta = self.manejar(OperationalError("database is locked"))
        self.assertEqual(respuesta.status_code, 409)

    def test_error_operacional_que_no_es_bloqueo_sigue_de_largo(self):
        self.assertIsNone(self.manejar(OperationalError("connection refused")))

    def test_integrity_error_da_409(self):
        respuesta = self.manejar(IntegrityError("duplicado"))
        self.assertEqual(respuesta.status_code, 409)

    def test_value_error_pelado_no_se_traduce(self):
        self.assertIsNone(self.manejar(ValueError("bug")))

    def test_excepciones_de_drf_usan_el_manejador_por_defecto(self):
        with mock.patch("config.exceptions.exception_handler") as por_defecto:
            exc = NotFound()
            manejador_excepciones(exc, {"view": None})
        por_defecto.assert_called_once_with(exc, {"view": None})


class PermisosTests(SimpleTestCase):
    def tiene(self, permiso, user, metodo="get"):
        return permiso().has_permission(_request(metodo, user), None)

    def test_admin_sistema_requiere_superusuario(self):
        self.assertTrue(self.tiene(EsAdminSistema, _usuario(is_superuser=True)))
        self.assertFalse(self.tiene(EsAdminSistema, _usuario(is_staff=True)))

    def test_admin_club_requiere_staff(self):
        self.assertTrue(self.tiene(EsAdminClub, _usuario(is_staff=True)))
        self.assertFalse(self.tiene(EsAdminClub, _usuario()))

    def test_jugador_requiere_perfil(self):
        self.assertTrue(self.tiene(EsJugador, _usuario(jugador=object())))
        self.assertFalse(self.tiene(EsJugador, _usuario()))

    def test_anonimo_no_tiene_ningun_permiso(self):
        anonimo = _usuario(
            is_authenticated=False, is_staff=True, is_superuser=True, jugador=object()
        )
        for permiso in (EsAdminSistema, EsAdminClub, EsJugador):
            with self.subTest(permiso=permiso.__name__):
                self.assertFalse(self.tiene(permiso, anonimo))
                self.assertFalse(self.tiene(permiso, None))

    def test_solo_lectura_permite_leer_a_cualquiera(self):
        anonimo = _usuario(is_authenticated=False)
        for metodo in ("get", "head", "options"):
            with self.subTest(metodo=metodo):
                self.assertTrue(self.tiene(SoloLecturaOAdminSistema, anonimo, metodo))

    def test_solo_lectura_exige_superusuario_para_escribir(self):
        for metodo in ("post", "put", "patch", "delete"):
            with self.subTest(metodo=metodo):
                self.assertFalse(self.tiene(SoloLecturaOAdminSistema, _usuario(is_staff=True), metodo))
                self.assertTrue(self.tiene(SoloLecturaOAdminSistema, _usuario(is_superuser=True), metodo))

    def test_cada_permiso_tiene_mensaje(self):
        for permiso in (EsAdminSistema, EsAdminClub, EsJugador, SoloLecturaOAdminSistema):
            self.assertTrue(permiso.message)


class NotificarTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.u1 = Usuario.objects.create_user("u1", "u1@x.com", "clave12345")
        cls.u2 = Usuario.objects.create_user("u2", "u2@x.com", "clave12345")

    def test_crea_una_notificacion_por_usuario(self):
        notificar([self.u1, self.u2], "hola")
        self.assertEqual(Notificacion.objects.filter(mensaje="hola").count(), 2)

    def test_acepta_ids_y_instancias(self):
        notificar([self.u1, self.u2.pk], "mixto")
        usuarios = set(Notificacion.objects.filter(mensaje="mixto").values_list("usuario_id", flat=True))
        self.assertEqual(usuarios, {self.u1.pk, self.u2.pk})

    def test_no_duplica_destinatarios(self):
        notificar([self.u1, self.u1.pk, self.u1], "una sola")
        self.assertEqual(Notificacion.objects.filter(mensaje="una sola").count(), 1)

    def test_sin_destinatarios_no_crea_nada(self):
        notificar([], "nadie")
        self.assertFalse(Notificacion.objects.exists())

    def test_nace_sin_leer(self):
        notificar([self.u1], "nueva")
        self.assertFalse(Notificacion.objects.get().leida)
