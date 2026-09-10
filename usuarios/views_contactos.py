# encoding: utf-8
"""
Vistas para la sección de contactos/amigos en Mi perfil.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import redirect
from django.views import View
from django.views.generic import ListView

from social.models import Contacto

from .models import Jugador


class BuscarJugadoresView(LoginRequiredMixin, ListView):
    """
    Devuelve una lista de jugadores disponibles para agregar como contacto.

    Filtra:
    - El propio jugador logueado
    - Jugadores que ya son contacto (inicios o recibidos, estado ACEPTADO)

    Soporta búsqueda por nombre/apellido/email via query param ``q``.
    """
    model = Jugador
    template_name = 'usuarios/_buscar_jugadores.html'
    context_object_name = 'jugadores'
    paginate_by = 20

    def get_queryset(self):
        jugador = self.request.user.jugador
        qs = Jugador.objects.exclude(pk=jugador.pk)

        # Excluir contactos ya existentes (bidireccional, estado ACEPTADO)
        contacto_ids = Contacto.objects.filter(
            estado=Contacto.Estado.ACEPTADO
        ).filter(
            Q(jugador=jugador) | Q(contacto=jugador)
        ).values_list('jugador', 'contacto').distinct()
        excluidos = set()
        for j, c in contacto_ids:
            excluidos.add(j)
            excluidos.add(c)
        excluidos.discard(jugador.pk)
        qs = qs.exclude(pk__in=excluidos)

        q = self.request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(nombre__icontains=q)
                | Q(apellido__icontains=q)
                | Q(usuario__email__icontains=q)
            ).order_by('nombre', 'apellido')
        else:
            qs = qs.order_by('nombre', 'apellido')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '').strip()
        return context


class RemoverContactoView(LoginRequiredMixin, View):
    """
    Elimina un Contacto (bidireccional: iniciado o recibido) del jugador logueado.

    POST con ``contacto_id`` — el PK del Jugador contacto a remover.
    """
    def post(self, request, *args, **kwargs):
        contacto_id = request.POST.get('contacto_id')
        if not contacto_id:
            messages.error(request, 'No se especificó el contacto a remover.')
            return redirect('usuarios:perfil')

        jugador = request.user.jugador
        try:
            contacto_jugador = Jugador.objects.get(pk=contacto_id)
        except Jugador.DoesNotExist:
            messages.error(request, 'El contacto solicitado no existe.')
            return redirect('usuarios:perfil')

        if contacto_id == str(jugador.pk):
            messages.error(request, 'No podés eliminarte a vos mismo.')
            return redirect('usuarios:perfil')

        # Borrar tanto si el jugador inició el contacto como si fue recibido
        borrados, _ = Contacto.objects.filter(
            estado=Contacto.Estado.ACEPTADO,
            jugador=jugador,
            contacto=contacto_jugador,
        ).delete()
        if borrados == 0:
            # También intentar el lado inverso (alguien más lo agregó a este jugador)
            Contacto.objects.filter(
                estado=Contacto.Estado.ACEPTADO,
                jugador=contacto_jugador,
                contacto=jugador,
            ).delete()

        messages.success(
            request,
            f'{contacto_jugador.nombre} {contacto_jugador.apellido} fue removido de tus contactos.',
        )
        return redirect('usuarios:perfil')
