import django_filters
from django.db.models import Q

from .models import Lobby


class LobbyFilter(django_filters.FilterSet):
    club = django_filters.NumberFilter(field_name="turno__cancha__club")
    zona = django_filters.NumberFilter(field_name="turno__cancha__club__zona")
    fecha = django_filters.DateFilter(field_name="turno__fecha")
    hora_desde = django_filters.TimeFilter(field_name="turno__hora_inicio", lookup_expr="gte")
    hora_hasta = django_filters.TimeFilter(field_name="turno__hora_inicio", lookup_expr="lte")
    con_cupos = django_filters.BooleanFilter(method="filtrar_con_cupos")
    precio_max = django_filters.NumberFilter(method="filtrar_precio_max")
    mios = django_filters.BooleanFilter(method="filtrar_mios")
    estado = django_filters.MultipleChoiceFilter(choices=Lobby.Estado.choices)
    orden = django_filters.OrderingFilter(fields=(("turno__inicio", "inicio"),))

    class Meta:
        model = Lobby
        fields = ["privacidad", "estado"]

    def filtrar_con_cupos(self, queryset, name, value):
        if value:
            return queryset.filter(ocupados__lt=Lobby.CANTIDAD_CUPOS)
        return queryset.filter(ocupados__gte=Lobby.CANTIDAD_CUPOS)

    def filtrar_precio_max(self, queryset, name, value):
        return queryset.filter(turno__precio__lte=value * Lobby.CANTIDAD_CUPOS)

    def filtrar_mios(self, queryset, name, value):
        jugador = self.request.user.jugador
        propios = Q(inscripciones__jugador=jugador)
        return queryset.filter(propios) if value else queryset.exclude(propios)
