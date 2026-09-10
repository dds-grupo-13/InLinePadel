from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView
from django.contrib.auth.mixins import LoginRequiredMixin

from partidas.models import Inscripcion, Lobby
from usuarios.models import Jugador

from .models import Invitacion


class InvitacionForm(forms.ModelForm):
	class Meta:
		model = Invitacion
		fields = ['jugador']
		labels = {'jugador': 'Selecciona el jugador a invitar'}
		widgets = {
			'jugador': forms.Select(attrs={
				'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200',
			}),
		}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.fields['jugador'].queryset = Jugador.objects.select_related('usuario').all()


class InvitacionCreateView(LoginRequiredMixin, CreateView):
	model = Invitacion
	form_class = InvitacionForm
	template_name = 'social/invitacion_form.html'

	def dispatch(self, request, *args, **kwargs):
		"""
		Valida que el usuario autenticado sea el capitán del lobby.
		"""
		jugador = getattr(request.user, 'jugador', None)
		if jugador is None:
			messages.error(request, 'Necesitás tener un perfil de jugador para enviar invitaciones.')
			return redirect('partidas:lobby_list')

		lobby = get_object_or_404(Lobby, pk=self.kwargs['lobby_id'])
		capitan = lobby.inscripciones.filter(numero_cupo=1).select_related('jugador').first()

		if capitan is None or capitan.jugador_id != jugador.pk:
			messages.error(request, 'Solo el capitán del lobby puede enviar invitaciones.')
			return redirect('partidas:lobby_detail', pk=lobby.pk)

		return super().dispatch(request, *args, **kwargs)

	def get_lobby(self):
		return get_object_or_404(Lobby, pk=self.kwargs['lobby_id'])

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		lobby = self.get_lobby()
		context['lobby'] = lobby
		context['inscripciones'] = lobby.inscripciones.select_related('jugador').all()
		context['cupos_disponibles'] = max(
			Lobby.CANTIDAD_CUPOS - context['inscripciones'].count(),
			0,
		)
		return context

	def form_valid(self, form):
		with transaction.atomic():
			lobby = get_object_or_404(
				Lobby.objects.select_for_update(),
				pk=self.kwargs['lobby_id'],
			)

			jugador_invitado = form.cleaned_data['jugador']

			# Validar que el jugador invitado no esté ya inscripto en el lobby
			if lobby.inscripciones.filter(jugador=jugador_invitado).exists():
				form.add_error('jugador', 'Este jugador ya está inscripto en el lobby.')
				return self.form_invalid(form)

			# Validar que no exista invitación pendiente
			if Invitacion.objects.filter(
				lobby=lobby,
				jugador=jugador_invitado,
				estado=Invitacion.Estado.PENDIENTE,
			).exists():
				form.add_error('jugador', 'Ya existe una invitación pendiente para este jugador.')
				return self.form_invalid(form)

			# Crear la invitación
			invitacion = form.save(commit=False)
			invitacion.lobby = lobby
			invitacion.jugador = jugador_invitado
			invitacion.emisor = getattr(self.request.user, 'jugador', None)
			invitacion.estado = Invitacion.Estado.PENDIENTE
			invitacion.save()

		messages.success(
			self.request,
			f'Invitación enviada a {jugador_invitado.usuario.email} correctamente.'
		)
		return redirect('partidas:lobby_detail', pk=lobby.pk)

	def get_success_url(self):
		return reverse_lazy('partidas:lobby_detail', kwargs={'pk': self.kwargs['lobby_id']})
