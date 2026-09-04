from django.shortcuts import get_object_or_404
from django.db.models import Count
from django.utils import timezone
from django.views.generic import ListView

from .models import Cancha, Club
from partidas.models import Lobby


class ClubListView(ListView):
	model = Club
	template_name = 'clubes/club_list.html'
	context_object_name = 'clubs'

	def get_queryset(self):
		clubs = list(Club.objects.filter(estado=Club.Estado.ACTIVO).prefetch_related('canchas').order_by('denominacion'))
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

		return clubs


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
	context_object_name = 'lobbies_activos'

	def get_cancha(self):
		return get_object_or_404(Cancha.objects.select_related('club'), pk=self.kwargs['cancha_id'])

	def get_queryset(self):
		cancha = self.get_cancha()
		fecha_actual = timezone.now().date()
		return (
			Lobby.objects
			.filter(
				estado=Lobby.Estado.EN_FORMACION,
				reserva__turno__cancha=cancha,
				reserva__turno__fecha__gte=fecha_actual,
			)
			.annotate(cupos_ocupados=Count('inscripciones'))
			.filter(cupos_ocupados__lt=Lobby.CANTIDAD_CUPOS)
			.select_related('reserva__turno')
			.prefetch_related('inscripciones')
			.order_by('reserva__turno__fecha', 'reserva__turno__hora_inicio')
		)

	def get_context_data(self, **kwargs):
		context = super().get_context_data(**kwargs)
		cancha = self.get_cancha()
		fecha_actual = timezone.now().date()
		turnos = cancha.turnos.filter(
			estado='LIBRE',
			fecha__gte=fecha_actual,
		).order_by('fecha', 'hora_inicio')
		context['cancha'] = cancha
		context['club'] = cancha.club
		context['turnos'] = turnos
		return context
