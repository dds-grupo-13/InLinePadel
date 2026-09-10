from django.test import TestCase
from django.urls import reverse
from django.core.management import call_command

from clubes.models import Cancha, Club, Turno
from partidas.models import Inscripcion, Lobby, Reserva
from social.models import Invitacion, SolicitudAcceso

from .models import Jugador, Usuario


class JugadorUpdateViewTests(TestCase):
	def setUp(self):
		self.user = Usuario.objects.create_user(email='jugador@example.com', password='secret123')

	def test_usuario_no_autenticado_redirige_a_login(self):
		"""Un usuario no autenticado es redirigido a la página de login."""
		response = self.client.get(reverse('usuarios:editar_perfil'))
		self.assertEqual(response.status_code, 302)
		self.assertIn('/login/', response.url)

	def test_usuario_autenticado_puede_acceder_al_formulario(self):
		"""Un usuario autenticado puede acceder al formulario de edición de perfil."""
		self.client.force_login(self.user)
		response = self.client.get(reverse('usuarios:editar_perfil'))
		self.assertEqual(response.status_code, 200)
		self.assertTemplateUsed(response, 'usuarios/perfil_form.html')

	def test_se_crea_perfil_automaticamente_si_no_existe(self):
		"""El perfil de Jugador se crea automáticamente si no existe."""
		self.assertFalse(Jugador.objects.filter(usuario=self.user).exists())

		self.client.force_login(self.user)
		response = self.client.get(reverse('usuarios:editar_perfil'))

		self.assertEqual(response.status_code, 200)
		self.assertTrue(Jugador.objects.filter(usuario=self.user).exists())

	def test_usuario_puede_actualizar_su_perfil(self):
		"""Un usuario puede actualizar su información de jugador."""
		# Crear perfil inicial
		jugador = Jugador.objects.create(
			usuario=self.user,
			nombre='Juan',
			apellido='Pérez',
			zona='Centro',
		)

		self.client.force_login(self.user)

		response = self.client.post(
			reverse('usuarios:editar_perfil'),
			{
				'nombre': 'Carlos',
				'apellido': 'García',
				'zona': 'Norte',
				'posicion_preferida': 'DRIVE',
			},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)

		jugador.refresh_from_db()
		self.assertEqual(jugador.nombre, 'Carlos')
		self.assertEqual(jugador.apellido, 'García')
		self.assertEqual(jugador.zona, 'Norte')
		self.assertEqual(jugador.posicion_preferida, 'DRIVE')

	def test_bola_prevention_usuario_solo_puede_editar_su_perfil(self):
		"""Cada usuario solo puede editar su propio perfil (BOLA prevention)."""
		otro_user = Usuario.objects.create_user(email='otro@example.com', password='secret123')
		otro_jugador = Jugador.objects.create(
			usuario=otro_user,
			nombre='Otro',
			apellido='Jugador',
			zona='Sur',
		)

		self.client.force_login(self.user)

		# Intentar acceder como este usuario solo recuperará su propio perfil
		response = self.client.get(reverse('usuarios:editar_perfil'))
		self.assertEqual(response.status_code, 200)

		# La instancia obtenida debe ser la del usuario autenticado, no la de otro_user
		form = response.context['form']
		self.assertEqual(form.instance.usuario, self.user)

	def test_campos_requeridos_no_pueden_estar_vacios(self):
		"""Los campos requeridos no pueden quedar vacíos."""
		jugador = Jugador.objects.create(
			usuario=self.user,
			nombre='Juan',
			apellido='Pérez',
			zona='Centro',
		)

		self.client.force_login(self.user)

		response = self.client.post(
			reverse('usuarios:editar_perfil'),
			{
				'nombre': '',
				'apellido': 'García',
				'zona': 'Norte',
				'posicion_preferida': 'DRIVE',
			},
		)

		# El formulario debe tener errores
		self.assertEqual(response.status_code, 200)
		self.assertIn('nombre', response.context['form'].errors)

class DemoDataTests(TestCase):
    def setUp(self):
        super().setUp()
        self.user = Usuario.objects.create_user(email='jugador@example.com', password='secret123')
        self.jugador = Jugador.objects.create(
            usuario=self.user,
            nombre='Juan',
            apellido='Perez',
            zona='Centro',
        )

    def test_seed_demo_data_creates_demo_content(self):
        call_command('seed_demo_data')

        self.assertTrue(Usuario.objects.filter(email='demo@inlinepadel.com').exists())
        self.assertTrue(Club.objects.exists())
        self.assertTrue(Cancha.objects.exists())
        self.assertTrue(Turno.objects.exists())
        self.assertTrue(Lobby.objects.exists())
        self.assertTrue(Reserva.objects.exists())
        self.assertTrue(Inscripcion.objects.exists())
        self.assertTrue(Invitacion.objects.exists())
        self.assertTrue(SolicitudAcceso.objects.exists())

    def test_demo_login_autentica_al_usuario_demo(self):
        call_command('seed_demo_data')

        response = self.client.post(
            reverse('login'),
            {'email': 'demo@inlinepadel.com', 'password': 'demo123'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue('_auth_user_id' in self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            Usuario.objects.get(email='demo@inlinepadel.com').pk,
        )

    def test_demo_login_acepta_password_legacy_de_demo(self):
        call_command('seed_demo_data')

        response = self.client.post(
            reverse('login'),
            {'email': 'demo@inlinepadel.com', 'password': 'demo'},
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue('_auth_user_id' in self.client.session)
        self.assertEqual(
            int(self.client.session['_auth_user_id']),
            Usuario.objects.get(email='demo@inlinepadel.com').pk,
        )

    def test_se_crea_contacto_al_agregar_desde_perfil(self):
        import social.models
        otro_user = Usuario.objects.create_user(
            email='amigo@example.com',
            password='secret123',
        )
        otro_jugador = Jugador.objects.create(
            usuario=otro_user,
            nombre='Ana',
            apellido='Gomez',
            zona='Belgrano',
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('usuarios:perfil_agregar_contacto'),
            {'amigo_id': str(otro_jugador.pk)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            social.models.Contacto.objects.filter(
                jugador=self.jugador,
                contacto=otro_jugador,
                estado=social.models.Contacto.Estado.ACEPTADO,
            ).exists()
        )

    def test_perfil_muestra_contactos_iniciados_y_recibidos(self):
        import social.models
        otro_user = Usuario.objects.create_user(
            email='amigo@example.com',
            password='secret123',
        )
        otro_jugador = Jugador.objects.create(
            usuario=otro_user,
            nombre='Ana',
            apellido='Gomez',
            zona='Belgrano',
        )
        social.models.Contacto.objects.create(
            jugador=self.jugador,
            contacto=otro_jugador,
            estado=social.models.Contacto.Estado.ACEPTADO,
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse('usuarios:perfil'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['contactos_iniciados'].count(), 1)
        self.assertEqual(response.context['contactos_iniciados'].first().pk, otro_jugador.pk)
        self.assertEqual(response.context['contactos_recibidos'].count(), 0)

    def test_remover_contacto_elimina_relacion(self):
        import social.models
        otro_user = Usuario.objects.create_user(
            email='amigo@example.com',
            password='secret123',
        )
        otro_jugador = Jugador.objects.create(
            usuario=otro_user,
            nombre='Ana',
            apellido='Gomez',
            zona='Belgrano',
        )
        contacto = social.models.Contacto.objects.create(
            jugador=self.jugador,
            contacto=otro_jugador,
            estado=social.models.Contacto.Estado.ACEPTADO,
        )
        self.client.force_login(self.user)
        response = self.client.post(
            reverse('usuarios:perfil_remover_contacto'),
            {'contacto_id': str(otro_jugador.pk)},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(social.models.Contacto.objects.filter(pk=contacto.pk).exists())
        self.assertEqual(response.context['contactos_iniciados'].count(), 0)

    def test_buscar_jugadores_excluye_propio_y_contactos(self):
        import social.models
        otro_user = Usuario.objects.create_user(
            email='amigo@example.com',
            password='secret123',
        )
        otro_jugador = Jugador.objects.create(
            usuario=otro_user,
            nombre='Ana',
            apellido='Gomez',
            zona='Belgrano',
        )
        social.models.Contacto.objects.create(
            jugador=self.jugador,
            contacto=otro_jugador,
            estado=social.models.Contacto.Estado.ACEPTADO,
        )
        tercer_user = Usuario.objects.create_user(
            email='tercero@example.com',
            password='secret123',
        )
        tercer_jugador = Jugador.objects.create(
            usuario=tercer_user,
            nombre='Luis',
            apellido='Ferraro',
            zona='Caballito',
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('usuarios:perfil_buscar') + '?q=Fer',
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ferraro')
        self.assertNotContains(response, 'Gomez')
        self.assertNotContains(response, self.jugador.apellido)

    def test_buscar_jugadores_sin_query_devuelve_disponibles(self):
        import social.models
        otro_user = Usuario.objects.create_user(
            email='amigo@example.com',
            password='secret123',
        )
        Jugador.objects.create(
            usuario=otro_user,
            nombre='Ana',
            apellido='Gomez',
            zona='Belgrano',
        )
        self.client.force_login(self.user)
        response = self.client.get(
            reverse('usuarios:perfil_buscar'),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ana')

