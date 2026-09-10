from django import forms

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
            'plazo_limite': forms.DateTimeInput(attrs={'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900 focus:border-emerald-500 focus:outline-none focus:ring-2 focus:ring-emerald-200', 'type': 'datetime-local'}),
        }
        help_texts = {
            'plazo_limite': 'Fecha y hora límite para que se completen los cupos del lobby.',
        }

    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data
