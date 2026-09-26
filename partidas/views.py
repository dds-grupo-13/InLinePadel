import uuid
from datetime import datetime, timedelta

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import DatabaseError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin

from clubes.models import Turno
from social.models import SolicitudAcceso
from usuarios.models import Jugador

from .models import Inscripcion, Lobby, Reserva
from .forms import LobbyCreateForm


def _turnos_se_superponen(turno_a, turno_b):
	if turno_a.fecha != turno_b.fecha:
		return False

	inicio_a = datetime.combine(turno_a.fecha, turno_a.hora_inicio)
	fin_a = inicio_a + timedelta(minutes=turno_a.duracion)
	inicio_b = datetime.combine(turno_b.fecha, turno_b.hora_inicio)
	fin_b = inicio_b + timedelta(minutes=turno_b.duracion)
	return inicio_a < fin_b and inicio_b < fin_a


@login_required
def crear_lobby_y_reserva(request, turno_id):
	turno = get_object_or_404(
		Turno.objects.select_related('cancha__club'),
		pk=turno_id,
		estado=Turno.Estado.LIBRE,
	)
	jugador = getattr(request.user, 'jugador', None)
	if jugador is None:
		messages.error(request, 'Necesitás tener un perfil de jugador para crear un lobby.')
		return redirect('clubes:cancha_detail', cancha_id=turno.cancha_id)

	if request.method == 'GET':
		if not turno.esta_disponible_para_reserva():
			messages.error(request, 'El turno seleccionado ya no está disponible.')
			return redirect('clubes:cancha_detail', cancha_id=turno.cancha_id)
		return render(request, 'partidas/lobby_form.html', {'form': LobbyCreateForm(), 'turno': turno})

	form = LobbyCreateForm(request.POST)
	if not form.is_valid():
		return render(request, 'partidas/lobby_form.html', {'form': form, 'turno': turno})

	try:
		with transaction.atomic():
			jugador = Jugador.objects.select_for_update().get(pk=jugador.pk)
			reservas_activas = Inscripcion.objects.filter(
				jugador=jugador,
				rol=Inscripcion.Rol.CAPITAN,
				lobby__estado__in=[Lobby.Estado.EN_FORMACION, Lobby.Estado.COMPLETO],
				lobby__reserva__estado__in=[Reserva.Estado.PROVISORIA, Reserva.Estado.CONFIRMADA],
			).count()
			if reservas_activas >= 2:
				messages.error(request, 'Solo podés tener hasta 2 canchas reservadas activas.')
				return redirect('clubes:cancha_detail', cancha_id=turno.cancha_id)

			turno = Turno.objects.select_for_update(nowait=True).get(
				id=turno_id,
				estado=Turno.Estado.LIBRE,
			)
			if not turno.esta_disponible_para_reserva():
				raise DatabaseError('El turno seleccionado ya no está disponible.')

			lobby = form.save(commit=False)
			lobby.plazo_limite = timezone.now() + timedelta(days=2)
			lobby.estado = Lobby.Estado.EN_FORMACION
			lobby.save()
			Reserva.objects.create(
				lobby=lobby,
				turno=turno,
				estado=Reserva.Estado.PROVISORIA,
				codigo_reserva=None,
			)
			turno.estado = Turno.Estado.BLOQUEADO
			turno.save(update_fields=['estado'])
			Inscripcion.objects.create(
				lobby=lobby,
				jugador=jugador,
				numero_cupo=1,
				rol=Inscripcion.Rol.CAPITAN,
			)
	except DatabaseError:
		messages.error(request, 'El turno ya no está disponible. Elegí otro turno.')
		return redirect('clubes:cancha_detail', cancha_id=turno.cancha_id)

	messages.success(request, 'La reserva y el lobby fueron creados correctamente.')
	return redirect('partidas:lobby_detail', pk=lobby.pk)


class ReservaForm(forms.ModelForm):
	class Meta:
		model = Reserva
		fields = ['lobby']
		labels = {'lobby': 'Lobby'}
		widgets = {
			'lobby': forms.Select(attrs={
				'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200',
			}),
		}


class ReservaCreateView(CreateView):
	model = Reserva
	form_class = ReservaForm
	template_name = 'partidas/reserva_form.html'

	def get_turno(self):
		return get_object_or_404(
			Turno.objects.select_related('cancha__club'),
			pk=self.kwargs['turno_id'],
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['turno'] = self.get_turno()
		return context

	def form_valid(self, form):
		with transaction.atomic():
			turno = get_object_or_404(
				Turno.objects.select_for_update(),
				pk=self.kwargs['turno_id'],
			)
			if turno.estado != Turno.Estado.LIBRE or not turno.esta_disponible_para_reserva():
				form.add_error(None, 'El turno seleccionado ya no está disponible.')
				return self.form_invalid(form)

			lobby = get_object_or_404(
				Lobby.objects.select_for_update(),
				pk=form.cleaned_data['lobby'].pk,
			)
			reserva = form.save(commit=False)
			reserva.lobby = lobby
			reserva.turno = turno
			reserva.estado = Reserva.Estado.PROVISORIA
			reserva.codigo_reserva = None

			if lobby.cupos_ocupados() >= Lobby.CANTIDAD_CUPOS:
				reserva.estado = Reserva.Estado.CONFIRMADA
				reserva.codigo_reserva = f'RES-{uuid.uuid4().hex[:12].upper()}'

			reserva.save()

			turno.estado = (
				Turno.Estado.CONFIRMADO
				if reserva.estado == Reserva.Estado.CONFIRMADA
				else Turno.Estado.BLOQUEADO
			)
			turno.save(update_fields=['estado'])

		messages.success(self.request, 'La reserva fue creada correctamente.')
		return redirect(self.get_success_url())

	def get_success_url(self):
		return self.request.path


class LobbyDetailView(DetailView):
	model = Lobby
	template_name = 'partidas/lobby_detail.html'

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		lobby = self.object
		inscripciones = list(lobby.inscripciones.select_related('jugador').all())
		jugador = getattr(self.request.user, 'jugador', None)
		capitan = lobby.inscripciones.filter(numero_cupo=1).select_related('jugador__usuario').first()

		context['inscripciones'] = inscripciones
		context['cupos_disponibles'] = max(
			Lobby.CANTIDAD_CUPOS - len(inscripciones),
			0,
		)
		context['ya_inscripto'] = (
			jugador is not None
			and any(inscripcion.jugador_id == jugador.pk for inscripcion in inscripciones)
		)
		context['puede_unirse'] = (
			jugador is not None
			and not context['ya_inscripto']
			and context['cupos_disponibles'] > 0
			and lobby.estado == Lobby.Estado.EN_FORMACION
		)
		context['es_capitan'] = (
			jugador is not None
			and capitan is not None
			and capitan.jugador_id == jugador.pk
		)
		context['cupos'] = [
			{'numero': numero, 'ocupado': numero <= len(inscripciones)}
			for numero in range(1, Lobby.CANTIDAD_CUPOS + 1)
		]
		return context


class AceptarSolicitudView(LoginRequiredMixin, View):
	def post(self, request, *args, **kwargs):
		jugador = getattr(request.user, 'jugador', None)
		if jugador is None:
			messages.error(request, 'Necesitás tener un perfil de jugador para gestionar solicitudes.')
			return redirect('partidas:lobby_list')

		solicitud = get_object_or_404(
			SolicitudAcceso.objects.select_related('lobby', 'jugador__usuario'),
			pk=self.kwargs['pk'],
		)

		capitan = get_object_or_404(
			Inscripcion.objects.select_related('jugador__usuario'),
			lobby=solicitud.lobby,
			numero_cupo=1,
		)
		if capitan.jugador_id != jugador.pk:
			messages.error(request, 'Solo el capitán del lobby puede aceptar solicitudes.')
			return redirect('partidas:lobby_detail', pk=solicitud.lobby_id)

		with transaction.atomic():
			lobby = get_object_or_404(
				Lobby.objects.select_for_update(),
				pk=solicitud.lobby_id,
			)
			inscripciones = list(
				Inscripcion.objects.select_for_update().filter(lobby=lobby)
			)

			if len(inscripciones) >= Lobby.CANTIDAD_CUPOS:
				messages.error(request, 'Este lobby ya está completo.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			solicitud = SolicitudAcceso.objects.select_for_update().get(pk=solicitud.pk)
			if solicitud.estado != SolicitudAcceso.Estado.PENDIENTE:
				messages.error(request, 'La solicitud ya no se encuentra pendiente.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			if any(inscripcion.jugador_id == solicitud.jugador_id for inscripcion in inscripciones):
				messages.error(request, 'El jugador ya se encuentra inscripto en este lobby.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			cupos_ocupados = {inscripcion.numero_cupo for inscripcion in inscripciones}
			nuevo_cupo = next(
				numero for numero in range(1, Lobby.CANTIDAD_CUPOS + 1)
				if numero not in cupos_ocupados
			)
			Inscripcion.objects.create(
				lobby=lobby,
				jugador=solicitud.jugador,
				numero_cupo=nuevo_cupo,
				rol=Inscripcion.Rol.JUGADOR,
			)
			solicitud.estado = SolicitudAcceso.Estado.ACEPTADA
			solicitud.save(update_fields=['estado'])

			if len(inscripciones) + 1 >= Lobby.CANTIDAD_CUPOS:
				lobby.estado = Lobby.Estado.COMPLETO
				lobby.save(update_fields=['estado'])

		messages.success(request, 'La solicitud fue aceptada y el jugador fue incorporado al lobby.')
		return redirect('partidas:lobby_detail', pk=lobby.pk)


class LobbyListView(ListView):
	model = Lobby
	template_name = 'partidas/lobby_list.html'
	context_object_name = 'lobbies'

	def get_queryset(self):
		queryset = (
			Lobby.objects
			.filter(estado=Lobby.Estado.EN_FORMACION)
			.annotate(cupos_ocupados=Count('inscripciones'))
			.filter(cupos_ocupados__lt=Lobby.CANTIDAD_CUPOS)
			.select_related('reserva__turno__cancha__club')
			.prefetch_related('inscripciones')
		)

		club_id = self.request.GET.get('club_id')
		if club_id:
			queryset = queryset.filter(reserva__turno__cancha__club_id=club_id)

		return queryset


class InscripcionCreateView(LoginRequiredMixin, CreateView):
	model = Inscripcion
	fields = []
	http_method_names = ['post']

	def post(self, request, *args, **kwargs):
		jugador = getattr(request.user, 'jugador', None)
		if jugador is None:
			messages.error(request, 'El usuario actual no tiene un perfil de jugador.')
			return redirect('partidas:lobby_list')

		with transaction.atomic():
			lobby = get_object_or_404(
				Lobby.objects.select_for_update(),
				pk=self.kwargs['lobby_id'],
			)
			if lobby.estado != Lobby.Estado.EN_FORMACION:
				messages.error(request, 'El lobby no está disponible para nuevas inscripciones.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			inscripciones = list(
				Inscripcion.objects.select_for_update().filter(lobby=lobby)
			)
			if any(inscripcion.jugador_id == jugador.pk for inscripcion in inscripciones):
				messages.error(request, 'Ya estás inscripto en este lobby.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			if len(inscripciones) >= Lobby.CANTIDAD_CUPOS:
				messages.error(request, 'El lobby ya está completo.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			turno_nuevo = get_object_or_404(
				Reserva.objects.select_related('turno'),
				lobby=lobby,
			).turno
			participaciones_activas = (
				Inscripcion.objects
				.filter(
					jugador=jugador,
					lobby__estado__in=[Lobby.Estado.EN_FORMACION, Lobby.Estado.COMPLETO],
					lobby__reserva__estado__in=[Reserva.Estado.PROVISORIA, Reserva.Estado.CONFIRMADA],
				)
				.exclude(lobby=lobby)
				.select_related('lobby__reserva__turno')
			)
			if any(
				_turnos_se_superponen(turno_nuevo, inscripcion.lobby.reserva.turno)
				for inscripcion in participaciones_activas
			):
				messages.error(request, 'No podés unirte: el horario se superpone con otro lobby en el que participás.')
				return redirect('partidas:lobby_detail', pk=lobby.pk)

			cupos_ocupados = {inscripcion.numero_cupo for inscripcion in inscripciones}
			numero_cupo = next(
				numero for numero in range(1, Lobby.CANTIDAD_CUPOS + 1)
				if numero not in cupos_ocupados
			)
			Inscripcion.objects.create(
				lobby=lobby,
				jugador=jugador,
				numero_cupo=numero_cupo,
				rol=Inscripcion.Rol.JUGADOR,
			)

			if len(inscripciones) + 1 == Lobby.CANTIDAD_CUPOS:
				reserva = get_object_or_404(
					Reserva.objects.select_for_update().select_related('turno'),
					lobby=lobby,
				)
				reserva.estado = Reserva.Estado.CONFIRMADA
				reserva.codigo_reserva = f'RES-{uuid.uuid4().hex[:12].upper()}'
				reserva.save(update_fields=['estado', 'codigo_reserva'])

				lobby.estado = Lobby.Estado.COMPLETO
				lobby.save(update_fields=['estado'])
				reserva.turno.estado = Turno.Estado.CONFIRMADO
				reserva.turno.save(update_fields=['estado'])

		messages.success(request, 'Te incorporaste al lobby correctamente.')
		return redirect('partidas:lobby_detail', pk=lobby.pk)

class MisPartidosListView(LoginRequiredMixin, ListView):
	model = Inscripcion
	template_name = 'partidas/mis_partidos.html'
	context_object_name = 'inscripciones'

	def get_queryset(self):
		return (
			Inscripcion.objects
			.filter(jugador__usuario=self.request.user)
			.select_related('lobby__reserva__turno__cancha__club')
			.order_by('lobby__fecha_creacion')
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		reservas = (
			Reserva.objects
			.filter(lobby__inscripciones__jugador__usuario=self.request.user)
			.select_related('lobby', 'turno__cancha__club')
			.distinct()
			.order_by('turno__fecha', 'turno__hora_inicio')
		)
		context['reservas_provisorias'] = reservas.filter(
			estado=Reserva.Estado.PROVISORIA,
		)
		context['reservas_confirmadas'] = reservas.filter(
			estado=Reserva.Estado.CONFIRMADA,
		)
		context['reservas_total'] = (
			context['reservas_provisorias'].count()
			+ context['reservas_confirmadas'].count()
		)
		context['lobbies_activos'] = (
			Lobby.objects
			.filter(
				inscripciones__jugador__usuario=self.request.user,
				estado__in=[Lobby.Estado.EN_FORMACION, Lobby.Estado.COMPLETO],
			)
			.select_related('reserva__turno__cancha__club')
			.prefetch_related('inscripciones')
			.distinct()
			.order_by('-fecha_creacion')
		)
		return context


class LobbyUpdateForm(forms.ModelForm):
    class Meta:
        model = Lobby
        fields = [
            'privacidad',
            'plazo_limite',
        ]
        labels = {
            'privacidad': 'Privacidad',
            'plazo_limite': 'Plazo límite para completar los cupos',
        }
        widgets = {
            'privacidad': forms.Select(attrs={'class': 'form-input'}),
            'plazo_limite': forms.DateTimeInput(
                attrs={'class': 'form-input', 'type': 'datetime-local'},
                format='%Y-%m-%dT%H:%M',
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plazo_limite'].input_formats = ['%Y-%m-%dT%H:%M']


class LobbyUpdateView(LoginRequiredMixin, UpdateView):
	model = Lobby
	form_class = LobbyUpdateForm
	template_name = 'partidas/lobby_form.html'

	def get_object(self, queryset=None):
		return get_object_or_404(
			Lobby.objects.select_related('reserva__turno__cancha__club'),
			reserva__pk=self.kwargs['reserva_id'],
			inscripciones__jugador__usuario=self.request.user,
			inscripciones__numero_cupo=1,
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['reserva'] = get_object_or_404(
			Reserva.objects.select_related('turno__cancha__club'),
			pk=self.kwargs['reserva_id'],
			lobby__inscripciones__jugador__usuario=self.request.user,
			lobby__inscripciones__numero_cupo=1,
		)
		return context

	def form_valid(self, form):
		with transaction.atomic():
			lobby = get_object_or_404(
				Lobby.objects.select_for_update(),
				pk=self.object.pk,
				reserva__pk=self.kwargs['reserva_id'],
				inscripciones__jugador__usuario=self.request.user,
				inscripciones__numero_cupo=1,
			)
			if lobby.estado != Lobby.Estado.EN_FORMACION:
				form.add_error(None, 'Solo se puede configurar un lobby en formación.')
				return self.form_invalid(form)

			form.instance = lobby
			lobby = form.save(commit=False)
			lobby.estado = Lobby.Estado.EN_FORMACION
			lobby.save()
			self.object = lobby

		messages.success(self.request, 'La configuración del lobby fue actualizada.')
		return redirect(reverse_lazy('partidas:lobby_detail', kwargs={'pk': lobby.pk}))


class ReservaCancelView(LoginRequiredMixin, DetailView):
	model = Reserva
	template_name = 'partidas/reserva_confirm_cancel.html'

	def get_object(self, queryset=None):
		"""
		Recupera de forma segura la reserva verificando que el usuario autenticado
		sea el capitán del lobby asociado (numero_cupo=1) para prevenir BOLA.
		"""
		return get_object_or_404(
			Reserva.objects.select_related('lobby', 'turno__cancha__club'),
			pk=self.kwargs['pk'],
			lobby__inscripciones__jugador__usuario=self.request.user,
			lobby__inscripciones__numero_cupo=1,
		)

	def post(self, request, *args, **kwargs):
		"""
		Maneja la cancelación de la reserva con lógica transaccional segura.
		"""
		self.object = self.get_object()

		with transaction.atomic():
			# Re-fetch con select_for_update para evitar race conditions
			reserva = Reserva.objects.select_for_update().get(pk=self.object.pk)

			# Cambiar estado de la Reserva a CANCELADA
			reserva.estado = Reserva.Estado.CANCELADA
			reserva.save(update_fields=['estado'])

			# Cambiar estado del Lobby a CANCELADO
			lobby = Lobby.objects.select_for_update().get(pk=reserva.lobby_id)
			lobby.estado = Lobby.Estado.CANCELADO
			lobby.save(update_fields=['estado'])

			# Liberar el Turno cambiando su estado a LIBRE
			turno = Turno.objects.select_for_update().get(pk=reserva.turno_id)
			turno.estado = Turno.Estado.LIBRE
			turno.save(update_fields=['estado'])

		messages.success(request, 'La reserva fue cancelada correctamente y el turno fue liberado.')
		return redirect(reverse_lazy('partidas:mis_partidos'))


class ReservaCheckInView(LoginRequiredMixin, View):
	"""Registra el check-in para reservas confirmadas y actualiza el turno asociado."""

	def get(self, request, *args, **kwargs):
		reserva = get_object_or_404(
			Reserva.objects.select_related('lobby', 'turno__cancha__club'),
			pk=self.kwargs['pk'],
			lobby__inscripciones__jugador__usuario=request.user,
			lobby__inscripciones__numero_cupo=1,
		)
		if reserva.estado != Reserva.Estado.CONFIRMADA:
			messages.error(request, 'La reserva solo puede hacer check-in si está confirmada.')
			return redirect('partidas:mis_partidos')
		return self.render_to_response({'object': reserva})

	def render_to_response(self, context):
		return render(self.request, 'partidas/reserva_checkin.html', context)

	def post(self, request, *args, **kwargs):
		jugador = getattr(request.user, 'jugador', None)
		if jugador is None:
			messages.error(request, 'Necesitás tener un perfil de jugador para registrar el check-in.')
			return redirect('partidas:mis_partidos')

		reserva = get_object_or_404(
			Reserva.objects.select_related('lobby', 'turno'),
			pk=self.kwargs['pk'],
		)

		if reserva.estado != Reserva.Estado.CONFIRMADA:
			messages.error(request, 'La reserva solo puede hacer check-in si está confirmada.')
			return redirect('partidas:mis_partidos')

		if not Inscripcion.objects.filter(
			lobby=reserva.lobby,
			jugador=jugador,
			numero_cupo=1,
		).exists():
			messages.error(request, 'Solo el capitán del lobby puede registrar el check-in.')
			return redirect('partidas:mis_partidos')

		with transaction.atomic():
			reserva_locked = Reserva.objects.select_for_update().get(pk=reserva.pk)
			if reserva_locked.estado != Reserva.Estado.CONFIRMADA:
				messages.error(request, 'La reserva ya no está en estado confirmado.')
				return redirect('partidas:mis_partidos')

			turno = Turno.objects.select_for_update().get(pk=reserva_locked.turno_id)
			reserva_locked.estado = Reserva.Estado.CUMPLIDA
			reserva_locked.fecha_check_in = timezone.now()
			reserva_locked.save(update_fields=['estado', 'fecha_check_in'])

			turno.estado = Turno.Estado.CUMPLIDO
			turno.save(update_fields=['estado'])

			lobby = Lobby.objects.select_for_update().get(pk=reserva_locked.lobby_id)
			lobby.estado = Lobby.Estado.JUGADO
			lobby.save(update_fields=['estado'])

		messages.success(request, 'El check-in fue registrado correctamente.')
		return redirect('partidas:mis_partidos')
