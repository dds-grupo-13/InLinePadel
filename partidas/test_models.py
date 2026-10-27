import re
from datetime import timedelta
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from clubes.models import Club, Turno
from config.exceptions import Conflicto, ErrorDominio
from config.test_utils import BaseAPITestCase
from partidas.models import Inscripcion, Lobby
from social.models import Invitacion, Notificacion, SolicitudAcceso


class LobbyBaseTestCase(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.capitan = self.jugador("capitan")
        self.turno_libre = self.turno(self.cancha, dias=3, hora=20)

    def lobby_completo(self, turno=None):
        lobby = Lobby.crear(turno or self.turno_libre, self.capitan)
        for nombre in ("j2", "j3", "j4"):
            lobby.inscribir(self.jugador(nombre))
        return lobby


class LobbyCrearTests(LobbyBaseTestCase):
    def test_crea_lobby_en_formacion_con_capitan_inscripto_en_el_cupo_1(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        self.assertEqual(lobby.estado, Lobby.Estado.EN_FORMACION)
        self.assertEqual(lobby.capitan, self.capitan)
        inscripcion = lobby.inscripciones.get()
        self.assertEqual((inscripcion.jugador, inscripcion.numero_cupo), (self.capitan, 1))

    def test_bloquea_el_turno(self):
        Lobby.crear(self.turno_libre, self.capitan)
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.turno_libre.estado, Turno.Estado.BLOQUEADO)

    def test_plazo_es_48_horas_y_check_in_es_el_inicio_del_turno(self):
        antes = timezone.now()
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        esperado = antes + timedelta(hours=Lobby.HORAS_PLAZO)
        self.assertAlmostEqual(
            lobby.plazo_limite.timestamp(), esperado.timestamp(), delta=5
        )
        self.assertEqual(lobby.fecha_check_in, self.turno_libre.inicio)

    def test_plazo_no_pasa_del_inicio_del_turno(self):
        corto = Turno.objects.create(
            cancha=self.cancha,
            fecha=(timezone.localtime() + timedelta(days=1)).date(),
            hora_inicio=(timezone.localtime() + timedelta(hours=1)).time(),
            precio=1000,
        )
        if corto.inicio <= timezone.now():
            self.skipTest("el turno cae del otro lado de la medianoche")
        lobby = Lobby.crear(corto, self.capitan)
        self.assertLessEqual(lobby.plazo_limite, corto.inicio)

    def test_notifica_al_admin_del_club(self):
        Lobby.crear(self.turno_libre, self.capitan)
        self.assertEqual(
            Notificacion.objects.filter(usuario=self.admin, mensaje__contains="provisoriamente").count(),
            1,
        )

    def test_rechaza_club_no_activo(self):
        Club.objects.filter(pk=self.club.pk).update(estado=Club.Estado.SUSPENDIDO)
        self.turno_libre.cancha.club.refresh_from_db()
        with self.assertRaises(ErrorDominio):
            Lobby.crear(self.turno_libre, self.capitan)

    def test_rechaza_cancha_inactiva(self):
        self.cancha.activa = False
        self.cancha.save()
        with self.assertRaises(ErrorDominio):
            Lobby.crear(self.turno_libre, self.capitan)

    def test_rechaza_turno_pasado(self):
        pasado = self.turno(self.cancha, dias=-2, hora=10)
        with self.assertRaises(ErrorDominio):
            Lobby.crear(pasado, self.capitan)

    def test_turno_tomado_da_conflicto(self):
        Lobby.crear(self.turno_libre, self.capitan)
        otro = self.jugador("otro")
        with self.assertRaises(Conflicto):
            Lobby.crear(self.turno_libre, otro)

    def test_limite_de_lobbies_en_formacion(self):
        for dia in range(1, Lobby.MAX_LOBBIES_EN_FORMACION + 1):
            Lobby.crear(self.turno(self.cancha, dias=10 + dia, hora=9), self.capitan)
        with self.assertRaises(ErrorDominio):
            Lobby.crear(self.turno(self.cancha, dias=20, hora=9), self.capitan)

    def test_rechaza_horario_superpuesto_del_capitan(self):
        Lobby.crear(self.turno_libre, self.capitan)
        superpuesto = self.turno(self.otra_cancha, dias=3, hora=20)
        with self.assertRaises(Conflicto):
            Lobby.crear(superpuesto, self.capitan)

    def test_turno_ocupado_da_mensaje_segun_su_estado(self):
        casos = (
            (Turno.Estado.BLOQUEADO, Conflicto, "ya fue tomado"),
            (Turno.Estado.CONFIRMADO, Conflicto, "ya fue tomado"),
            (Turno.Estado.NO_DISPONIBLE, Conflicto, "retiró este turno"),
            (Turno.Estado.CUMPLIDO, ErrorDominio, "ya pasó"),
        )
        for i, (estado, excepcion, texto) in enumerate(casos):
            with self.subTest(estado=estado):
                turno = self.turno(self.cancha, dias=7, hora=8 + 3 * i)
                Turno.objects.filter(pk=turno.pk).update(estado=estado)
                turno.refresh_from_db()
                turno.estado = Turno.Estado.LIBRE
                with self.assertRaises(excepcion) as ctx:
                    Lobby.crear(turno, self.jugador(f"cap_{estado}"))
                self.assertIs(type(ctx.exception), excepcion)
                self.assertIn(texto, str(ctx.exception))

    def test_mensaje_de_superposicion_usa_hora_local(self):
        Lobby.crear(self.turno(self.cancha, dias=5, hora=19), self.capitan)
        with self.assertRaises(ErrorDominio) as ctx:
            Lobby.crear(self.turno(self.otra_cancha, dias=5, hora=19), self.capitan)
        self.assertIn("19:00", str(ctx.exception))

    def test_falla_atomica_no_deja_el_turno_bloqueado(self):
        antes = self.turno_libre.inicio
        with self.assertRaises(ValidationError):
            Lobby.crear(
                self.turno_libre,
                self.capitan,
                fecha_check_in=antes + timedelta(hours=1),
            )
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.turno_libre.estado, Turno.Estado.LIBRE)
        self.assertFalse(Lobby.objects.exists())

    def test_privacidad_por_defecto_publica(self):
        self.assertEqual(Lobby.crear(self.turno_libre, self.capitan).privacidad, Lobby.Privacidad.PUBLICO)

    def test_acepta_privacidad_privada(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan, privacidad=Lobby.Privacidad.PRIVADO)
        self.assertEqual(lobby.privacidad, Lobby.Privacidad.PRIVADO)


class LobbyCleanTests(LobbyBaseTestCase):
    def armar(self, plazo, check_in):
        return Lobby(
            turno=self.turno_libre,
            capitan=self.capitan,
            plazo_limite=plazo,
            fecha_check_in=check_in,
        )

    def test_plazo_posterior_al_check_in_es_invalido(self):
        inicio = self.turno_libre.inicio
        with self.assertRaises(ValidationError):
            self.armar(inicio, inicio - timedelta(minutes=5)).clean()

    def test_check_in_posterior_al_inicio_es_invalido(self):
        inicio = self.turno_libre.inicio
        with self.assertRaises(ValidationError):
            self.armar(inicio, inicio + timedelta(minutes=5)).clean()

    def test_plazo_igual_al_check_in_es_valido(self):
        inicio = self.turno_libre.inicio
        self.armar(inicio, inicio).clean()

    def test_clean_con_campos_faltantes_no_falla(self):
        Lobby().clean()

    def test_str(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        self.assertIn(f"Lobby {lobby.pk}", str(lobby))
        self.assertIn("[EN_FORMACION]", str(lobby))


class ConflictoHorarioTests(LobbyBaseTestCase):
    def test_sin_lobbies_no_hay_conflicto(self):
        self.assertIsNone(Lobby.conflicto_horario(self.capitan, self.turno_libre))

    def test_detecta_lobby_superpuesto(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        superpuesto = self.turno(self.otra_cancha, dias=3, hora=20)
        self.assertEqual(Lobby.conflicto_horario(self.capitan, superpuesto), lobby)

    def test_turno_contiguo_no_es_conflicto(self):
        Lobby.crear(self.turno_libre, self.capitan)
        contiguo = Turno.objects.create(
            cancha=self.otra_cancha,
            fecha=self.turno_libre.fecha,
            hora_inicio=timezone.localtime(self.turno_libre.fin).time(),
            precio=1000,
        )
        self.assertIsNone(Lobby.conflicto_horario(self.capitan, contiguo))

    def test_ignora_lobbies_cancelados(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        lobby.cancelar_por_capitan(lobby.capitan)
        self.assertIsNone(Lobby.conflicto_horario(self.capitan, self.turno_libre))

    def test_excluir_lobby(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        self.assertIsNone(
            Lobby.conflicto_horario(self.capitan, self.turno_libre, excluir_lobby=lobby.pk)
        )

    def test_otro_jugador_no_tiene_conflicto(self):
        Lobby.crear(self.turno_libre, self.capitan)
        self.assertIsNone(Lobby.conflicto_horario(self.jugador("libre"), self.turno_libre))


class LobbyInscribirTests(LobbyBaseTestCase):
    def setUp(self):
        super().setUp()
        self.lobby = Lobby.crear(self.turno_libre, self.capitan)

    def test_asigna_el_primer_cupo_libre(self):
        inscripcion = self.lobby.inscribir(self.jugador("j2"))
        self.assertEqual(inscripcion.numero_cupo, 2)

    def test_reutiliza_cupo_liberado(self):
        j2, j3 = self.jugador("j2"), self.jugador("j3")
        self.lobby.inscribir(j2)
        self.lobby.inscribir(j3)
        self.lobby.abandonar(j2)
        self.assertEqual(self.lobby.inscribir(self.jugador("j4")).numero_cupo, 2)

    def test_jugador_ya_inscripto(self):
        with self.assertRaises(ErrorDominio):
            self.lobby.inscribir(self.capitan)

    def test_horario_superpuesto_da_conflicto(self):
        j2 = self.jugador("j2")
        otro_turno = self.turno(self.otra_cancha, dias=3, hora=20)
        Lobby.crear(otro_turno, j2)
        with self.assertRaises(Conflicto):
            self.lobby.inscribir(j2)

    def test_mensaje_de_superposicion_al_inscribir_usa_hora_local(self):
        j2 = self.jugador("j2")
        Lobby.crear(self.turno(self.otra_cancha, dias=5, hora=19), j2)
        lobby = Lobby.crear(self.turno(self.cancha, dias=5, hora=19), self.jugador("cap2"))
        with self.assertRaises(Conflicto) as ctx:
            lobby.inscribir(j2)
        self.assertIn("19:00", str(ctx.exception))

    def test_no_confirma_si_el_lobby_se_cancelo_mientras_ocupaba_el_ultimo_cupo(self):
        for nombre in ("j2", "j3"):
            self.lobby.inscribir(self.jugador(nombre))

        def cancelar_en_paralelo(*args, **kwargs):
            Lobby.objects.filter(pk=self.lobby.pk).update(estado=Lobby.Estado.CANCELADO)

        with mock.patch.object(Lobby, "conflicto_horario", side_effect=cancelar_en_paralelo):
            with self.assertRaises(Conflicto):
                self.lobby.inscribir(self.jugador("j4"))
        lobby = Lobby.objects.get(pk=self.lobby.pk)
        self.assertIsNone(lobby.codigo_reserva)
        self.assertEqual(lobby.inscripciones.count(), 3)
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.turno_libre.estado, Turno.Estado.BLOQUEADO)
        self.assertFalse(
            Notificacion.objects.filter(mensaje__startswith="Reserva confirmada").exists()
        )

    def test_lobby_cancelado_no_acepta_jugadores(self):
        self.lobby.cancelar_por_capitan(self.lobby.capitan)
        with self.assertRaises(Conflicto):
            self.lobby.inscribir(self.jugador("j2"))

    def test_el_cuarto_jugador_completa_y_confirma(self):
        for nombre in ("j2", "j3"):
            self.lobby.inscribir(self.jugador(nombre))
        self.assertEqual(self.lobby.estado, Lobby.Estado.EN_FORMACION)
        self.assertIsNone(self.lobby.codigo_reserva)
        self.lobby.inscribir(self.jugador("j4"))
        self.assertEqual(self.lobby.estado, Lobby.Estado.COMPLETO)
        self.lobby.refresh_from_db()
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.lobby.estado, Lobby.Estado.COMPLETO)
        self.assertEqual(self.turno_libre.estado, Turno.Estado.CONFIRMADO)
        self.assertRegex(self.lobby.codigo_reserva, r"^[0-9A-F]{4}-[0-9A-F]{4}$")

    def test_confirmar_notifica_a_jugadores_y_club(self):
        self.lobby_completo_en(self.lobby)
        for usuario in [self.capitan.usuario, self.admin]:
            self.assertTrue(
                Notificacion.objects.filter(usuario=usuario).exclude(
                    mensaje__contains="provisoriamente"
                ).exists()
            )
        codigo = self.lobby.codigo_reserva
        self.assertTrue(
            Notificacion.objects.filter(usuario=self.capitan.usuario, mensaje__contains=codigo).exists()
        )

    def test_completar_vence_pedidos_pendientes(self):
        privado = Lobby.crear(
            self.turno(self.cancha, dias=4, hora=20),
            self.jugador("cap2"),
            privacidad=Lobby.Privacidad.PRIVADO,
        )
        invitado = self.jugador("invitado")
        pendiente = Invitacion.objects.create(
            lobby=privado, emisor=privado.capitan, receptor=invitado
        )
        for nombre in ("a", "b", "c"):
            privado.inscribir(self.jugador(nombre))
        pendiente.refresh_from_db()
        self.assertEqual(pendiente.estado, Invitacion.Estado.EXPIRADA)

    def test_lobby_completo_no_acepta_a_un_quinto(self):
        self.lobby_completo_en(self.lobby)
        with self.assertRaises(Conflicto):
            self.lobby.inscribir(self.jugador("quinto"))

    def lobby_completo_en(self, lobby):
        for nombre in ("j2", "j3", "j4"):
            lobby.inscribir(self.jugador(nombre))


class LobbyAbandonarTests(LobbyBaseTestCase):
    def setUp(self):
        super().setUp()
        self.lobby = Lobby.crear(self.turno_libre, self.capitan)
        self.j2 = self.jugador("j2")
        self.lobby.inscribir(self.j2)

    def test_libera_el_cupo(self):
        self.lobby.abandonar(self.j2)
        self.assertFalse(self.lobby.inscripciones.filter(jugador=self.j2).exists())

    def test_no_inscripto_da_error(self):
        with self.assertRaises(ErrorDominio):
            self.lobby.abandonar(self.jugador("ajeno"))

    def test_lobby_cancelado_no_se_abandona(self):
        self.lobby.cancelar_por_capitan(self.lobby.capitan)
        with self.assertRaises(ErrorDominio):
            self.lobby.abandonar(self.j2)

    def test_capitan_cede_la_capitania_al_primero_inscripto(self):
        self.lobby.abandonar(self.capitan)
        self.assertEqual(self.lobby.capitan, self.j2)

    def test_si_no_queda_nadie_el_lobby_se_cancela_y_libera_el_turno(self):
        self.lobby.abandonar(self.j2)
        self.lobby.abandonar(self.capitan)
        self.assertEqual(self.lobby.estado, Lobby.Estado.CANCELADO)
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.turno_libre.estado, Turno.Estado.LIBRE)

    def test_abandono_de_lobby_completo_lo_reabre(self):
        for nombre in ("j3", "j4"):
            self.lobby.inscribir(self.jugador(nombre))
        self.assertEqual(self.lobby.estado, Lobby.Estado.COMPLETO)
        self.lobby.abandonar(self.j2)
        self.lobby.refresh_from_db()
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.lobby.estado, Lobby.Estado.EN_FORMACION)
        self.assertIsNone(self.lobby.codigo_reserva)
        self.assertEqual(self.turno_libre.estado, Turno.Estado.BLOQUEADO)

    def test_reapertura_concede_plazo_minimo(self):
        for nombre in ("j3", "j4"):
            self.lobby.inscribir(self.jugador(nombre))
        Lobby.objects.filter(pk=self.lobby.pk).update(plazo_limite=timezone.now() - timedelta(hours=1))
        self.lobby.abandonar(self.j2)
        self.lobby.refresh_from_db()
        minimo = timezone.now() + timedelta(hours=Lobby.HORAS_PLAZO_REAPERTURA)
        self.assertAlmostEqual(
            self.lobby.plazo_limite.timestamp(),
            min(minimo, self.lobby.fecha_check_in).timestamp(),
            delta=5,
        )


class LobbyCancelarTests(LobbyBaseTestCase):
    def test_cancelar_libera_el_turno_y_notifica(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        lobby.cancelar_por_capitan(lobby.capitan)
        lobby.refresh_from_db()
        self.turno_libre.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
        self.assertEqual(self.turno_libre.estado, Turno.Estado.LIBRE)
        self.assertTrue(
            Notificacion.objects.filter(usuario=self.capitan.usuario, mensaje__contains="Se canceló").exists()
        )

    def test_el_capitan_no_puede_cancelar_un_lobby_completo(self):
        lobby = self.lobby_completo()
        with self.assertRaises(Conflicto) as ctx:
            lobby.cancelar_por_capitan(self.capitan)
        self.assertIn("bajarse hasta el", str(ctx.exception))
        lobby.refresh_from_db()
        self.turno_libre.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.COMPLETO)
        self.assertEqual(self.turno_libre.estado, Turno.Estado.CONFIRMADO)

    def test_solo_el_capitan_cancela(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        with self.assertRaises(ErrorDominio):
            lobby.cancelar_por_capitan(self.jugador("otro"))

    def test_cancelar_registra_quien_cancelo(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        lobby.cancelar_por_capitan(self.capitan)
        lobby.refresh_from_db()
        self.assertEqual(lobby.cancelada_por, Lobby.CanceladaPor.CAPITAN)

    def test_cancelar_dos_veces_da_error(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        lobby.cancelar_por_capitan(lobby.capitan)
        with self.assertRaises(ErrorDominio):
            lobby.cancelar_por_capitan(lobby.capitan)

    def test_cancelar_vence_invitaciones_y_solicitudes_pendientes(self):
        lobby = Lobby.crear(
            self.turno_libre, self.capitan, privacidad=Lobby.Privacidad.PRIVADO
        )
        invitacion = Invitacion.objects.create(
            lobby=lobby, emisor=self.capitan, receptor=self.jugador("inv")
        )
        lobby.cancelar_por_capitan(lobby.capitan)
        invitacion.refresh_from_db()
        self.assertEqual(invitacion.estado, Invitacion.Estado.EXPIRADA)

    def test_turno_cancelado_puede_reservarse_de_nuevo(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        lobby.cancelar_por_capitan(self.capitan)
        nuevo = Lobby.crear(self.turno_libre, self.jugador("otro"))
        self.assertEqual(nuevo.estado, Lobby.Estado.EN_FORMACION)


class CodigoReservaTests(LobbyBaseTestCase):
    def test_codigos_distintos_entre_lobbies(self):
        primero = self.lobby_completo()
        segundo_turno = self.turno(self.otra_cancha, dias=4, hora=20)
        segundo = Lobby.crear(segundo_turno, self.jugador("cap2"))
        for nombre in ("k2", "k3", "k4"):
            segundo.inscribir(self.jugador(nombre))
        self.assertNotEqual(primero.codigo_reserva, segundo.codigo_reserva)
        self.assertTrue(re.match(r"^[0-9A-F]{4}-[0-9A-F]{4}$", segundo.codigo_reserva))


class InscripcionTests(LobbyBaseTestCase):
    def setUp(self):
        super().setUp()
        self.lobby = Lobby.crear(self.turno_libre, self.capitan)

    def test_str(self):
        inscripcion = self.lobby.inscripciones.get()
        self.assertEqual(str(inscripcion), f"Cupo 1 - Lobby {self.lobby.pk}")

    def test_cupo_unico_por_lobby(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Inscripcion.objects.create(lobby=self.lobby, jugador=self.jugador("x"), numero_cupo=1)

    def test_jugador_unico_por_lobby(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Inscripcion.objects.create(lobby=self.lobby, jugador=self.capitan, numero_cupo=2)

    def test_cupo_fuera_de_rango(self):
        for cupo in (0, Lobby.CANTIDAD_CUPOS + 1):
            with self.subTest(cupo=cupo), self.assertRaises(IntegrityError), transaction.atomic():
                Inscripcion.objects.create(
                    lobby=self.lobby, jugador=self.jugador(f"r{cupo}"), numero_cupo=cupo
                )


class LobbyConstraintsTests(LobbyBaseTestCase):
    def test_un_solo_lobby_vigente_por_turno(self):
        Lobby.crear(self.turno_libre, self.capitan)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lobby.objects.create(
                turno=self.turno_libre,
                capitan=self.jugador("dup"),
                plazo_limite=self.turno_libre.inicio,
                fecha_check_in=self.turno_libre.inicio,
            )

    def test_plazo_posterior_al_check_in_viola_el_constraint(self):
        inicio = self.turno_libre.inicio
        with self.assertRaises(IntegrityError), transaction.atomic():
            Lobby.objects.create(
                turno=self.turno_libre,
                capitan=self.capitan,
                plazo_limite=inicio,
                fecha_check_in=inicio - timedelta(minutes=1),
            )


def acercar_inicio(lobby, horas):
    """Mueve el inicio del turno a `horas` desde ahora (sin pasar por Turno.save)."""
    inicio = timezone.now() + timedelta(hours=horas)
    Turno.objects.filter(pk=lobby.turno_id).update(
        inicio=inicio, fin=inicio + timedelta(minutes=90)
    )
    lobby.turno.refresh_from_db()


class CierreReservaTests(LobbyBaseTestCase):
    def turno_en(self, horas):
        ahora = timezone.localtime() + timedelta(hours=horas)
        return Turno.objects.create(
            cancha=self.cancha, fecha=ahora.date(),
            hora_inicio=ahora.time().replace(second=0, microsecond=0), precio=4000,
        )

    def test_cierre_es_tres_horas_antes_del_inicio(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        self.assertEqual(lobby.cierre, self.turno_libre.inicio - timedelta(hours=3))
        self.assertEqual(Lobby.cierre_de(self.turno_libre), lobby.cierre)

    def test_plazo_al_crear_no_supera_el_cierre(self):
        turno = self.turno_en(10)
        lobby = Lobby.crear(turno, self.capitan)
        self.assertLessEqual(lobby.plazo_limite, lobby.cierre)
        self.assertAlmostEqual(
            lobby.plazo_limite.timestamp(), lobby.cierre.timestamp(), delta=1
        )

    def test_partida_de_ultimo_momento_tiene_plazo_hasta_el_inicio(self):
        turno = self.turno_en(2)
        lobby = Lobby.crear(turno, self.capitan)
        self.assertEqual(lobby.plazo_limite, turno.inicio)

    def test_ultimo_momento_queda_firme_al_completarse(self):
        lobby = Lobby.crear(self.turno_en(2), self.capitan)
        for nombre in ("j2", "j3", "j4"):
            lobby.inscribir(self.jugador(nombre))
        lobby.refresh_from_db()
        self.assertTrue(lobby.es_firme())

    def test_es_firme_depende_del_estado_y_del_momento(self):
        lobby = self.lobby_completo()
        self.assertFalse(lobby.es_firme())
        self.assertTrue(lobby.es_firme(ahora=lobby.cierre))
        self.assertFalse(lobby.es_firme(ahora=lobby.cierre - timedelta(seconds=1)))
        en_formacion = Lobby.crear(self.turno(self.cancha, dias=9, hora=10), self.jugador("c2"))
        self.assertFalse(en_formacion.es_firme(ahora=en_formacion.cierre + timedelta(hours=1)))

    def test_puede_cancelar_y_puede_abandonar(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        j2 = self.jugador("j2")
        lobby.inscribir(j2)
        ajeno = self.jugador("ajeno")
        self.assertTrue(lobby.puede_cancelar(self.capitan))
        self.assertFalse(lobby.puede_cancelar(j2))
        self.assertTrue(lobby.puede_abandonar(j2))
        self.assertFalse(lobby.puede_abandonar(ajeno))
        for nombre in ("j3", "j4"):
            lobby.inscribir(self.jugador(nombre))
        self.assertFalse(lobby.puede_cancelar(self.capitan))
        self.assertTrue(lobby.puede_abandonar(j2))
        self.assertFalse(lobby.puede_abandonar(j2, ahora=lobby.cierre))

    def test_bajarse_antes_del_cierre_reabre_y_avisa_al_club(self):
        lobby = self.lobby_completo()
        j2 = Inscripcion.objects.get(lobby=lobby, numero_cupo=2).jugador
        Notificacion.objects.all().delete()
        lobby.abandonar(j2)
        lobby.refresh_from_db()
        self.turno_libre.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.EN_FORMACION)
        self.assertEqual(lobby.estado_reserva, "PROVISORIA")
        self.assertIsNone(lobby.codigo_reserva)
        self.assertEqual(self.turno_libre.estado, Turno.Estado.BLOQUEADO)
        self.assertLessEqual(lobby.plazo_limite, lobby.cierre)
        self.assertTrue(
            Notificacion.objects.filter(
                usuario=self.admin, mensaje__contains="volvió a provisoria"
            ).exists()
        )

    def test_reapertura_cerca_del_cierre_no_pasa_del_cierre(self):
        lobby = self.lobby_completo()
        acercar_inicio(lobby, 4)  # cierre en 1 h: menos que las 12 h de reapertura
        lobby = Lobby.objects.get(pk=lobby.pk)
        j2 = Inscripcion.objects.get(lobby=lobby, numero_cupo=2).jugador
        lobby.abandonar(j2)
        lobby.refresh_from_db()
        self.assertLessEqual(lobby.plazo_limite, lobby.cierre)

    def test_no_se_puede_bajar_de_una_reserva_firme(self):
        lobby = self.lobby_completo()
        acercar_inicio(lobby, 2)
        lobby = Lobby.objects.get(pk=lobby.pk)
        j2 = Inscripcion.objects.get(lobby=lobby, numero_cupo=2).jugador
        with self.assertRaises(Conflicto) as ctx:
            lobby.abandonar(j2)
        self.assertIn("ya es firme", str(ctx.exception))
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.COMPLETO)
        self.assertEqual(lobby.inscripciones.count(), 4)
        self.assertIsNotNone(lobby.codigo_reserva)

    def test_el_capitan_tampoco_cancela_una_reserva_firme(self):
        lobby = self.lobby_completo()
        acercar_inicio(lobby, 2)
        lobby = Lobby.objects.get(pk=lobby.pk)
        with self.assertRaises(Conflicto) as ctx:
            lobby.cancelar_por_capitan(self.capitan)
        self.assertIn("ya es firme", str(ctx.exception))

    def test_el_ultimo_que_sale_cancela_por_abandono(self):
        lobby = Lobby.crear(self.turno_libre, self.capitan)
        lobby.abandonar(self.capitan)
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
        self.assertEqual(lobby.cancelada_por, Lobby.CanceladaPor.ABANDONO)
        self.turno_libre.refresh_from_db()
        self.assertEqual(self.turno_libre.estado, Turno.Estado.LIBRE)

    def test_vencer_lobbies_marca_vencimiento(self):
        from io import StringIO

        from django.core.management import call_command

        lobby = Lobby.crear(self.turno_libre, self.capitan)
        Lobby.objects.filter(pk=lobby.pk).update(
            plazo_limite=timezone.now() - timedelta(minutes=1)
        )
        call_command("vencer_lobbies", stdout=StringIO())
        lobby.refresh_from_db()
        self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
        self.assertEqual(lobby.cancelada_por, Lobby.CanceladaPor.VENCIMIENTO)
