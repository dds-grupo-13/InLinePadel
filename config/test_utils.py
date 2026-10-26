from datetime import time, timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APITestCase

from clubes.models import Cancha, Club, Turno, Zona
from usuarios.models import Jugador, Usuario


class BaseAPITestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.zona = Zona.objects.create(nombre="Tigre")
        cls.admin = Usuario.objects.create_user(
            "admin_club", "ac@x.com", "clave12345", is_staff=True
        )
        cls.otro_admin = Usuario.objects.create_user(
            "otro_admin", "oa@x.com", "clave12345", is_staff=True
        )
        cls.superadmin = Usuario.objects.create_superuser("root", "root@x.com", "clave12345")
        cls.club = Club.objects.create(
            denominacion="Club A", direccion="Calle 1", zona=cls.zona, admin=cls.admin
        )
        cls.otro_club = Club.objects.create(
            denominacion="Club B", direccion="Calle 2", zona=cls.zona, admin=cls.otro_admin
        )
        cls.cancha = Cancha.objects.create(numero=1, club=cls.club)
        cls.otra_cancha = Cancha.objects.create(numero=1, club=cls.otro_club)

    def setUp(self):
        cache.clear()

    @staticmethod
    def jugador(nombre):
        usuario = Usuario.objects.create_user(nombre, f"{nombre}@x.com", "clave12345")
        return Jugador.objects.create(usuario=usuario)

    @staticmethod
    def turno(cancha, dias=3, hora=20, precio="4000"):
        fecha = (timezone.localtime() + timedelta(days=dias)).date()
        return Turno.objects.create(
            cancha=cancha, fecha=fecha, hora_inicio=time(hora), precio=Decimal(precio)
        )

    def login(self, usuario):
        self.client.force_authenticate(usuario)
