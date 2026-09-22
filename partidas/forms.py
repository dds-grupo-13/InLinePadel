from datetime import datetime

from django import forms
from django.utils import timezone

from .models import Lobby


class LobbyCreateForm(forms.ModelForm):
    class Meta:
        model = Lobby
        fields = [
            'privacidad',
            'plazo_limite',
        ]
        labels = {
            'privacidad': 'Privacidad del lobby',
            'plazo_limite': 'Plazo límite para completar los cupos',
        }
        widgets = {
            'privacidad': forms.Select(attrs={'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200'}),
            'plazo_limite': forms.DateTimeInput(attrs={'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200', 'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'),
        }
        help_texts = {
            'plazo_limite': 'Fecha y hora límite para que se completen los cupos del lobby. Tiene que ser antes del horario del partido.',
        }

    def __init__(self, *args, turno=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plazo_limite'].input_formats = ['%Y-%m-%dT%H:%M']
        self.turno = turno
        if turno is not None:
            inicio_partido = timezone.make_aware(datetime.combine(turno.fecha, turno.hora_inicio))
            self.fields['plazo_limite'].widget.attrs['max'] = inicio_partido.strftime('%Y-%m-%dT%H:%M')

    def clean_plazo_limite(self):
        plazo_limite = self.cleaned_data['plazo_limite']
        if self.turno is not None:
            inicio_partido = timezone.make_aware(datetime.combine(self.turno.fecha, self.turno.hora_inicio))
            if plazo_limite >= inicio_partido:
                raise forms.ValidationError('El plazo límite debe ser anterior al horario del partido.')
        if plazo_limite <= timezone.now():
            raise forms.ValidationError('El plazo límite debe ser una fecha futura.')
        return plazo_limite
