from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import UpdateView

from .forms import JugadorCasualForm
from .models import Jugador


class PerfilCasualView(LoginRequiredMixin, UpdateView):
	model = Jugador
	form_class = JugadorCasualForm
	template_name = 'usuarios/perfil_casual.html'

	def get_object(self, queryset=None):
		return self.request.user.jugador

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['amigos'] = self.object.contacto.all().order_by('nombre', 'apellido')
		return context

	def get_success_url(self):
		return reverse_lazy('usuarios:perfil')


class AgregarContactoView(LoginRequiredMixin, View):
	def post(self, request, *args, **kwargs):
		amigo_id = request.POST.get('amigo_id')
		jugador = request.user.jugador

		if str(amigo_id) == str(jugador.pk):
			messages.error(request, 'No podés agregarte a vos mismo como contacto.')
			return redirect('usuarios:perfil')

		amigo = get_object_or_404(Jugador, pk=amigo_id)
		jugador.contacto.add(amigo)
		messages.success(request, f'{amigo.nombre} {amigo.apellido} fue agregado a tus contactos.')
		return redirect('usuarios:perfil')


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
