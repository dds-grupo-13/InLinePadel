from django import forms

from .models import Lobby


class LobbyCreateForm(forms.ModelForm):
    class Meta:
        model = Lobby
        fields = [
            'privacidad',
            'rango_min',
            'rango_max',
            'admite_provisorios',
        ]
        labels = {
            'privacidad': 'Privacidad del lobby',
            'rango_min': 'Rango mínimo',
            'rango_max': 'Rango máximo',
            'admite_provisorios': 'Admitir jugadores sin puntaje consolidado',
        }
        widgets = {
            'privacidad': forms.Select(attrs={'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900'}),
            'rango_min': forms.NumberInput(attrs={'min': 1, 'max': 5, 'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900'}),
            'rango_max': forms.NumberInput(attrs={'min': 1, 'max': 5, 'class': 'w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-slate-900'}),
            'admite_provisorios': forms.CheckboxInput(attrs={'class': 'h-4 w-4 rounded border-slate-300 text-emerald-600'}),
        }
        help_texts = {
            'admite_provisorios': 'Permite el ingreso de jugadores nuevos con menos de 10 partidos registrados.',
        }

    def clean(self):
        cleaned_data = super().clean()
        rango_min = cleaned_data.get('rango_min')
        rango_max = cleaned_data.get('rango_max')
        if rango_min is not None and rango_max is not None and rango_min > rango_max:
            raise forms.ValidationError('El rango mínimo no puede superar al rango máximo.')
        return cleaned_data