from django import forms

from .models import Jugador


class JugadorCasualForm(forms.ModelForm):
    class Meta:
        model = Jugador
        fields = [
            'nombre',
            'apellido',
            'posicion_preferida',
            'zona',
            'categoria_manual',
        ]
        labels = {
            'nombre': 'Nombre',
            'apellido': 'Apellido',
            'posicion_preferida': 'Posición preferida',
            'zona': 'Zona',
            'categoria_manual': 'Categoría',
        }
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'w-full rounded-lg border border-slate-300 px-4 py-3'}),
            'apellido': forms.TextInput(attrs={'class': 'w-full rounded-lg border border-slate-300 px-4 py-3'}),
            'posicion_preferida': forms.Select(attrs={'class': 'w-full rounded-lg border border-slate-300 px-4 py-3'}),
            'zona': forms.TextInput(attrs={'class': 'w-full rounded-lg border border-slate-300 px-4 py-3'}),
            'categoria_manual': forms.Select(attrs={'class': 'w-full rounded-lg border border-slate-300 px-4 py-3'}),
        }