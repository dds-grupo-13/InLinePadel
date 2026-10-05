from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView
from django.contrib.auth.mixins import LoginRequiredMixin
import uuid

from clubes.models import Turno
from partidas.models import Inscripcion, Lobby, Reserva
from usuarios.models import Jugador

from .models import Contacto, Invitacion


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

	def __init__(self, *args, jugador_actual=None, **kwargs):
		super().__init__(*args, **kwargs)
		if jugador_actual:
			from django.db.models import Q

			contactos_ids = Contacto.objects.filter(
				Q(jugador=jugador_actual) | Q(contacto=jugador_actual),
				estado=Contacto.Estado.ACEPTADO,
			).values_list('jugador', 'contacto')

			ids = set()
			for jugador_id, contacto_id in contactos_ids:
				ids.add(jugador_id)
				ids.add(contacto_id)
			ids.discard(jugador_actual.pk)

			self.fields['jugador'].queryset = self.fields['jugador'].queryset.filter(
				pk__in=ids
			).order_by('nombre', 'apellido')


class InvitacionCreateView(LoginRequiredMixin, CreateView):
	model = Invitacion
	form_class = InvitacionForm
	template_name = 'social/invitacion_form.html'

	def get_form_kwargs(self):
		kwargs = super().get_form_kwargs()
		kwargs['jugador_actual'] = getattr(self.request.user, 'jugador', None)
		return kwargs

	def dispatch(self, request, *args, **kwargs):
		"""
		Valida que el usuario autenticado sea el capitán del lobby.
		"""
		jugador = getattr(request.user, 'jugador', None)
		if jugador is None:
			messages.error(request, 'Necesitás tener un perfil de jugador para enviar invitaciones.')
			return redirect('partidas:lobby_list')

		lobby = get_object_or_404(Lobby, pk=self.kwargs['lobby_id'])
		if lobby.capitan_id != jugador.pk:
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


class InvitacionesListView(LoginRequiredMixin, ListView):
	template_name = 'social/invitaciones_list.html'
	context_object_name = 'invitaciones'

	def get_queryset(self):
		return Invitacion.objects.filter(
			jugador__usuario=self.request.user,
			estado=Invitacion.Estado.PENDIENTE,
		).select_related('lobby__reserva__turno__cancha__club', 'emisor')


class ProcesarInvitacionView(LoginRequiredMixin, View):
	def post(self, request, *args, **kwargs):
		jugador = getattr(request.user, 'jugador', None)
		if jugador is None:
			messages.error(request, 'Necesitás tener un perfil de jugador para procesar invitaciones.')
			return redirect('social:mis_invitaciones')

		invitacion_id = request.POST.get('invitacion_id')
		accion = request.POST.get('accion')
		invitacion = get_object_or_404(
			Invitacion,
			pk=invitacion_id,
			jugador=jugador,
			estado=Invitacion.Estado.PENDIENTE,
		)

		if accion == 'rechazar':
			invitacion.estado = Invitacion.Estado.RECHAZADA
			invitacion.save(update_fields=['estado'])
			messages.success(request, 'La invitación fue rechazada.')
			return redirect('social:mis_invitaciones')

		if accion != 'aceptar':
			messages.error(request, 'La acción solicitada no es válida.')
			return redirect('social:mis_invitaciones')

		with transaction.atomic():
			invitacion = get_object_or_404(
				Invitacion.objects.select_for_update(),
				pk=invitacion.pk,
				jugador=jugador,
				estado=Invitacion.Estado.PENDIENTE,
			)
			lobby = Lobby.objects.select_for_update().get(pk=invitacion.lobby_id)
			inscripciones = list(
				Inscripcion.objects.select_for_update().filter(lobby=lobby)
			)

			if (
				len(inscripciones) >= Lobby.CANTIDAD_CUPOS
				or lobby.estado != Lobby.Estado.EN_FORMACION
			):
				invitacion.estado = Invitacion.Estado.EXPIRADA
				invitacion.save(update_fields=['estado'])
				messages.error(
					request,
					'El lobby ya no está disponible para aceptar invitaciones.',
				)
				return redirect('social:mis_invitaciones')

			cupos_ocupados = {inscripcion.numero_cupo for inscripcion in inscripciones}
			numero_cupo = next(
				numero for numero in range(1, Lobby.CANTIDAD_CUPOS + 1)
				if numero not in cupos_ocupados
			)
			Inscripcion.objects.create(
				lobby=lobby,
				jugador=jugador,
				numero_cupo=numero_cupo,
			)
			invitacion.estado = Invitacion.Estado.ACEPTADA
			invitacion.save(update_fields=['estado'])

			if len(inscripciones) + 1 == Lobby.CANTIDAD_CUPOS:
				lobby.estado = Lobby.Estado.COMPLETO
				lobby.save(update_fields=['estado'])

				reserva = Reserva.objects.select_for_update().get(pk=lobby.reserva_id)
				reserva.estado = Reserva.Estado.CONFIRMADA
				reserva.codigo_reserva = f'RES-{uuid.uuid4().hex[:12].upper()}'
				reserva.save(update_fields=['estado', 'codigo_reserva'])

				turno = Turno.objects.select_for_update().get(pk=reserva.turno_id)
				turno.estado = Turno.Estado.CONFIRMADO
				turno.save(update_fields=['estado'])

		messages.success(request, 'Aceptaste la invitación y te uniste al lobby.')
		return redirect('social:mis_invitaciones')
