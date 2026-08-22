from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import UpdateView

from .models import Jugador


class JugadorUpdateView(LoginRequiredMixin, UpdateView):
	model = Jugador
	fields = ['nombre', 'apellido', 'posicion_preferida', 'zona']
	template_name = 'usuarios/perfil_form.html'
	success_url = reverse_lazy('partidas:mis_partidos')

	def get_object(self, queryset=None):
		"""
		Recupera de forma segura el perfil de Jugador asociado al usuario actual.
		Crea automáticamente el perfil si no existe, previniendo vulnerabilidades BOLA.
		"""
		jugador, _ = Jugador.objects.get_or_create(
			usuario=self.request.user,
			defaults={
				'nombre': '',
				'apellido': '',
				'zona': '',
			},
		)
		return jugador
