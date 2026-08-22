from django.shortcuts import get_object_or_404
from django.db.models import Count
from django.views.generic import ListView

from .models import Cancha, Club
from partidas.models import Lobby


class ClubListView(ListView):
	model = Club
	template_name = 'clubes/club_list.html'
	context_object_name = 'clubs'

	def get_queryset(self):
		self.mode = self.request.GET.get('modo', 'crear')
		if self.mode not in {'crear', 'unirse'}:
			self.mode = 'crear'

		clubs = list(Club.objects.prefetch_related('canchas').order_by('denominacion'))
		open_lobbies = (
			Lobby.objects
			.filter(estado=Lobby.Estado.EN_FORMACION, reserva__isnull=False)
			.annotate(cupos_ocupados=Count('inscripciones'))
			.filter(cupos_ocupados__lt=Lobby.CANTIDAD_CUPOS)
			.select_related('reserva__turno__cancha__club')
		)

		lobbies_por_club = {}
		for lobby in open_lobbies:
			club = lobby.reserva.turno.cancha.club
			lobbies_por_club[club.pk] = lobbies_por_club.get(club.pk, 0) + 1

		for club in clubs:
			club.canchas_disponibles = club.canchas.exists()
			club.lobbies_abiertos = lobbies_por_club.get(club.pk, 0)

		if self.mode == 'unirse':
			clubs = [club for club in clubs if club.lobbies_abiertos > 0]

		return clubs

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['modo'] = getattr(self, 'mode', 'crear')
		return context


class CanchaListView(ListView):
	model = Cancha
	template_name = 'clubes/cancha_list.html'

	def get_queryset(self):
		return self.model.objects.filter(club_id=self.kwargs['club_id'])

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		context['club'] = get_object_or_404(Club, pk=self.kwargs['club_id'])
		return context


class CanchaDetailView(ListView):
	model = Lobby
	template_name = 'clubes/cancha_detail.html'
	context_object_name = 'lobbies_abiertos'

	def get_cancha(self):
		return get_object_or_404(Cancha.objects.select_related('club'), pk=self.kwargs['cancha_id'])

	def get_queryset(self):
		cancha = self.get_cancha()
		return (
			Lobby.objects
			.filter(
				estado=Lobby.Estado.EN_FORMACION,
				reserva__turno__cancha=cancha,
			)
			.annotate(cupos_ocupados=Count('inscripciones'))
			.filter(cupos_ocupados__lt=Lobby.CANTIDAD_CUPOS)
			.select_related('reserva__turno__cancha__club')
			.prefetch_related('inscripciones')
			.order_by('-fecha_creacion')
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		cancha = self.get_cancha()
		turnos = cancha.turnos.order_by('fecha', 'hora_inicio')
		context['cancha'] = cancha
		context['club'] = cancha.club
		context['turnos'] = turnos
		context['primer_turno_libre'] = turnos.filter(estado='LIBRE').first()
		return context
