from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import UpdateView

from social.models import Contacto

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
        jugador = self.object
        iniciados_ids = set(
            Contacto.objects.filter(
                estado=Contacto.Estado.ACEPTADO,
                jugador=jugador,
            ).values_list('contacto', flat=True)
        )
        recibidos_ids = set(
            Contacto.objects.filter(
                estado=Contacto.Estado.ACEPTADO,
                contacto=jugador,
            ).values_list('jugador', flat=True)
        )
        amigo_ids = iniciados_ids | recibidos_ids
        amigos = Jugador.objects.filter(pk__in=amigo_ids).distinct().order_by(
            'nombre', 'apellido'
        )
        contactos_iniciados = Jugador.objects.filter(pk__in=iniciados_ids).distinct().order_by(
            'nombre', 'apellido'
        )
        contactos_recibidos = Jugador.objects.filter(pk__in=recibidos_ids).distinct().order_by(
            'nombre', 'apellido'
        )
        context['amigos'] = amigos
        context['contactos_iniciados'] = contactos_iniciados
        context['contactos_recibidos'] = contactos_recibidos
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
        Contacto.objects.create(
            jugador=jugador,
            contacto=amigo,
            estado=Contacto.Estado.ACEPTADO,
        )
        messages.success(
            request,
            f'{amigo.nombre} {amigo.apellido} fue agregado a tus contactos.',
        )
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
