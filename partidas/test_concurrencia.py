import threading
from time import sleep
from datetime import time, timedelta
from decimal import Decimal
from unittest import skipUnless

from django.db import OperationalError, connection
from django.test import TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from clubes.models import Cancha, Club, Turno, Zona
from config.exceptions import Conflicto, _es_falla_de_bloqueo
from partidas.models import Inscripcion, Lobby
from social.models import Invitacion
from usuarios.models import Jugador, Usuario


@skipUnless(
    connection.vendor == "postgresql",
    "La concurrencia real (RNF02) solo se puede validar contra PostgreSQL.",
)
class ConcurrenciaTests(TransactionTestCase):
    def setUp(self):
        zona = Zona.objects.create(nombre="Tigre")
        admin = Usuario.objects.create_user("admin_club", "ac@x.com", "clave12345", is_staff=True)
        club = Club.objects.create(
            denominacion="Club A", direccion="Calle 1", zona=zona, admin=admin
        )
        self.cancha = Cancha.objects.create(numero=1, club=club)
        self.turno = self.nuevo_turno()

    def nuevo_turno(self, dias=3, hora=20):
        fecha = (timezone.localtime() + timedelta(days=dias)).date()
        return Turno.objects.create(
            cancha=self.cancha, fecha=fecha, hora_inicio=time(hora), precio=Decimal("4000")
        )

    @staticmethod
    def jugador(nombre):
        usuario = Usuario.objects.create_user(nombre, f"{nombre}@x.com", "clave12345")
        return Jugador.objects.create(usuario=usuario)

    @staticmethod
    def en_paralelo(tareas):
        """Corre cada tarea en su hilo, todas arrancan juntas; devuelve los resultados.

        Cada resultado es ("ok", valor), ("conflicto", mensaje) o ("error", excepción).
        Una falla de bloqueo cuenta como conflicto: la API la responde con 409.
        """
        barrera = threading.Barrier(len(tareas))
        resultados = [None] * len(tareas)

        def correr(i, tarea):
            try:
                barrera.wait()
                resultados[i] = ("ok", tarea())
            except Conflicto as e:
                resultados[i] = ("conflicto", str(e))
            except OperationalError as e:
                if _es_falla_de_bloqueo(e):
                    resultados[i] = ("conflicto", str(e))
                else:
                    resultados[i] = ("error", e)
            except Exception as e:
                resultados[i] = ("error", e)
            finally:
                connection.close()

        hilos = [threading.Thread(target=correr, args=(i, t)) for i, t in enumerate(tareas)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join()
        return resultados

    def test_a_cincuenta_solicitudes_sobre_el_ultimo_cupo_dan_un_exito(self):
        lobby = Lobby.crear(self.turno, self.jugador("capitan"))
        for nombre in ("j2", "j3"):
            lobby.inscribir(self.jugador(nombre))
        aspirantes = [self.jugador(f"aspirante{n}") for n in range(50)]

        resultados = self.en_paralelo(
            [
                (lambda j=j: Lobby.objects.get(pk=lobby.pk).inscribir(j))
                for j in aspirantes
            ]
        )

        self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
        self.assertEqual(sum(r[0] == "ok" for r in resultados), 1)
        self.assertEqual(sum(r[0] == "conflicto" for r in resultados), 49)
        lobby.refresh_from_db()
        self.assertEqual(lobby.inscripciones.count(), 4)
        self.assertEqual(lobby.estado, Lobby.Estado.COMPLETO)
        self.assertIsNotNone(lobby.codigo_reserva)
        self.assertEqual(Lobby.objects.exclude(codigo_reserva=None).count(), 1)
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, Turno.Estado.CONFIRMADO)

    def test_b_veinte_capitanes_sobre_el_mismo_turno_dan_un_lobby(self):
        capitanes = [self.jugador(f"capitan{n}") for n in range(20)]

        resultados = self.en_paralelo(
            [(lambda c=c: Lobby.crear(Turno.objects.get(pk=self.turno.pk), c)) for c in capitanes]
        )

        self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
        self.assertEqual(sum(r[0] == "ok" for r in resultados), 1)
        self.assertEqual(sum(r[0] == "conflicto" for r in resultados), 19)
        self.assertEqual(Lobby.objects.count(), 1)
        self.turno.refresh_from_db()
        self.assertEqual(self.turno.estado, Turno.Estado.BLOQUEADO)

    def test_c_cancelar_en_formacion_y_ocupar_el_ultimo_cupo_ganan_uno_solo(self):
        for ronda in range(10):
            with self.subTest(ronda=ronda):
                turno = self.nuevo_turno(dias=10 + ronda, hora=9)
                capitan = self.jugador(f"cap{ronda}")
                lobby = Lobby.crear(turno, capitan)
                for nombre in ("j2", "j3"):
                    lobby.inscribir(self.jugador(f"{nombre}_{ronda}"))
                ultimo = self.jugador(f"ultimo{ronda}")

                resultados = self.en_paralelo(
                    [
                        lambda: Lobby.objects.get(pk=lobby.pk).cancelar_por_capitan(capitan),
                        lambda: Lobby.objects.get(pk=lobby.pk).inscribir(ultimo),
                    ]
                )

                self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
                cancelar, inscribir = resultados
                # Exactamente uno de los dos pudo hacer su operación.
                self.assertEqual([cancelar[0], inscribir[0]].count("ok"), 1)
                lobby.refresh_from_db()
                turno.refresh_from_db()
                if cancelar[0] == "ok":
                    self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
                    self.assertIsNone(lobby.codigo_reserva)
                    self.assertEqual(lobby.inscripciones.count(), 3)
                    self.assertEqual(turno.estado, Turno.Estado.LIBRE)
                else:
                    self.assertEqual(lobby.estado, Lobby.Estado.COMPLETO)
                    self.assertIsNotNone(lobby.codigo_reserva)
                    self.assertEqual(lobby.inscripciones.count(), 4)
                    self.assertEqual(turno.estado, Turno.Estado.CONFIRMADO)

    def test_d_bajarse_y_ocupar_el_ultimo_cupo_terminan_en_formacion(self):
        for ronda in range(10):
            with self.subTest(ronda=ronda):
                turno = self.nuevo_turno(dias=10 + ronda, hora=9)
                lobby = Lobby.crear(turno, self.jugador(f"cap{ronda}"))
                j2 = self.jugador(f"j2_{ronda}")
                lobby.inscribir(j2)
                lobby.inscribir(self.jugador(f"j3_{ronda}"))
                ultimo = self.jugador(f"ultimo{ronda}")

                resultados = self.en_paralelo(
                    [
                        lambda: Lobby.objects.get(pk=lobby.pk).abandonar(j2),
                        lambda: Lobby.objects.get(pk=lobby.pk).inscribir(ultimo),
                    ]
                )

                self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
                self.assertEqual([r[0] for r in resultados], ["ok", "ok"])
                lobby.refresh_from_db()
                turno.refresh_from_db()
                # Se complete antes o después, el que se bajó deja un cupo libre.
                self.assertEqual(lobby.estado, Lobby.Estado.EN_FORMACION)
                self.assertEqual(lobby.inscripciones.count(), 3)
                self.assertIsNone(lobby.codigo_reserva)
                self.assertEqual(turno.estado, Turno.Estado.BLOQUEADO)

    def test_e_aceptar_una_cesion_y_cancelar_el_club_terminan_consistentes(self):
        for ronda in range(10):
            with self.subTest(ronda=ronda):
                turno = self.nuevo_turno(dias=10 + ronda, hora=9)
                capitan = self.jugador(f"cap{ronda}")
                lobby = Lobby.crear(turno, capitan)
                emisor = self.jugador(f"emisor{ronda}")
                lobby.inscribir(emisor)
                for nombre in ("j3", "j4"):
                    lobby.inscribir(self.jugador(f"{nombre}_{ronda}"))
                receptor = self.jugador(f"receptor{ronda}")
                cesion = Invitacion(
                    lobby=lobby, emisor=emisor, receptor=receptor, reemplaza=emisor
                )
                cesion.save()

                resultados = self.en_paralelo(
                    [
                        lambda: Invitacion.objects.get(pk=cesion.pk).aceptar(),
                        lambda: Lobby.objects.get(pk=lobby.pk)._cancelar(
                            Lobby.CanceladaPor.CLUB, "Lluvia fuerte", Turno.Estado.NO_DISPONIBLE
                        ),
                    ]
                )

                self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
                aceptar, cancelar = resultados
                self.assertEqual(cancelar[0], "ok")
                lobby.refresh_from_db()
                cesion.refresh_from_db()
                self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
                self.assertEqual(lobby.inscripciones.count(), 4)
                en_lobby = Inscripcion.objects.filter(lobby=lobby)
                if aceptar[0] == "ok":
                    self.assertTrue(en_lobby.filter(jugador=receptor).exists())
                    self.assertFalse(en_lobby.filter(jugador=emisor).exists())
                    self.assertEqual(cesion.estado, Invitacion.Estado.ACEPTADA)
                else:
                    self.assertFalse(en_lobby.filter(jugador=receptor).exists())
                    self.assertTrue(en_lobby.filter(jugador=emisor).exists())
                    self.assertEqual(cesion.estado, Invitacion.Estado.EXPIRADA)

    def test_f_quince_unirse_por_http_sobre_el_ultimo_cupo_dan_un_200_y_catorce_409(self):
        # Varias rondas: los perdedores que llegan después de que el ganador
        # confirmó son los que, con la vista vieja, recibían 404.
        for ronda in range(5):
            with self.subTest(ronda=ronda):
                turno = self.nuevo_turno(dias=10 + ronda, hora=9)
                lobby = Lobby.crear(turno, self.jugador(f"capitan{ronda}"))
                for nombre in ("j2", "j3"):
                    lobby.inscribir(self.jugador(f"{nombre}_{ronda}"))
                aspirantes = [self.jugador(f"aspirante{ronda}_{n}") for n in range(15)]

                def unirse(demora, jugador, lobby=lobby):
                    # Llegadas escalonadas: algunas ocurren cuando el ganador ya confirmó.
                    sleep(demora)
                    cliente = APIClient()
                    cliente.force_authenticate(jugador.usuario)
                    return cliente.post(f"/api/partidas/lobbies/{lobby.pk}/unirse/").status_code

                resultados = self.en_paralelo([(lambda n=n, j=j: unirse(0.02 * n, j)) for n, j in enumerate(aspirantes)])

                self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
                codigos = sorted(r[1] for r in resultados if r[0] == "ok")
                self.assertEqual(codigos, [200] + [409] * 14)
                lobby.refresh_from_db()
                self.assertEqual(lobby.inscripciones.count(), 4)
                self.assertEqual(lobby.estado, Lobby.Estado.COMPLETO)
                self.assertIsNotNone(lobby.codigo_reserva)
        self.assertEqual(Lobby.objects.exclude(codigo_reserva=None).count(), 5)

    def test_g_unirse_al_ultimo_cupo_justo_cuando_vence_el_plazo_y_el_barrido(self):
        # El lobby termina COMPLETO o CANCELADO, nunca CANCELADO con 4 inscriptos.
        for ronda in range(5):
            with self.subTest(ronda=ronda):
                turno = self.nuevo_turno(dias=20 + ronda, hora=9)
                lobby = Lobby.crear(turno, self.jugador(f"cap_v{ronda}"))
                for nombre in ("j2", "j3"):
                    lobby.inscribir(self.jugador(f"{nombre}_v{ronda}"))
                ultimo = self.jugador(f"ultimo_v{ronda}")
                Lobby.objects.filter(pk=lobby.pk).update(
                    plazo_limite=timezone.now() + timedelta(milliseconds=150)
                )

                def unirse(lobby=lobby, ultimo=ultimo):
                    sleep(0.1)
                    return Lobby.objects.get(pk=lobby.pk).inscribir(ultimo)

                def barrer(lobby=lobby):
                    sleep(0.16)
                    return Lobby.objects.get(pk=lobby.pk).vencer_si_corresponde()

                resultados = self.en_paralelo([unirse, barrer])

                self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
                lobby.refresh_from_db()
                inscriptos = lobby.inscripciones.count()
                if lobby.estado == Lobby.Estado.COMPLETO:
                    self.assertEqual(inscriptos, 4)
                else:
                    self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
                    self.assertLess(inscriptos, 4)
