import threading
from datetime import time, timedelta
from decimal import Decimal
from unittest import skipUnless

from django.db import OperationalError, connection
from django.test import TransactionTestCase
from django.utils import timezone

from clubes.models import Cancha, Club, Turno, Zona
from config.exceptions import Conflicto, _es_falla_de_bloqueo
from partidas.models import Lobby
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

    def test_c_cancelar_y_ocupar_el_ultimo_cupo_nunca_dejan_estado_inconsistente(self):
        for ronda in range(10):
            with self.subTest(ronda=ronda):
                turno = self.nuevo_turno(dias=10 + ronda, hora=9)
                lobby = Lobby.crear(turno, self.jugador(f"cap{ronda}"))
                for nombre in ("j2", "j3"):
                    lobby.inscribir(self.jugador(f"{nombre}_{ronda}"))
                ultimo = self.jugador(f"ultimo{ronda}")

                resultados = self.en_paralelo(
                    [
                        lambda: Lobby.objects.get(pk=lobby.pk).cancelar(),
                        lambda: Lobby.objects.get(pk=lobby.pk).inscribir(ultimo),
                    ]
                )

                self.assertEqual([r[1] for r in resultados if r[0] == "error"], [])
                cancelar, inscribir = resultados
                self.assertEqual(cancelar[0], "ok")
                lobby.refresh_from_db()
                turno.refresh_from_db()
                self.assertEqual(lobby.estado, Lobby.Estado.CANCELADO)
                self.assertEqual(turno.estado, Turno.Estado.LIBRE)
                if inscribir[0] == "conflicto":
                    # La cancelación ganó: nadie confirmó nada.
                    self.assertIsNone(lobby.codigo_reserva)
                    self.assertEqual(lobby.inscripciones.count(), 3)
                else:
                    # El lobby se completó y recién después se canceló (regla
                    # vigente de cancelar un lobby COMPLETO).
                    self.assertEqual(lobby.inscripciones.count(), 4)
