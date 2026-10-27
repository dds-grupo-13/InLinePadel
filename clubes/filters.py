import django_filters
from django.db.models import Q

from .models import Turno


class TurnoFilter(django_filters.FilterSet):
    club = django_filters.NumberFilter(field_name="cancha__club")
    zona = django_filters.NumberFilter(field_name="cancha__club__zona")
    fecha = django_filters.DateFilter(field_name="fecha")
    fecha_desde = django_filters.DateFilter(field_name="fecha", lookup_expr="gte")
    fecha_hasta = django_filters.DateFilter(field_name="fecha", lookup_expr="lte")
    hora_desde = django_filters.TimeFilter(field_name="hora_inicio", lookup_expr="gte")
    hora_hasta = django_filters.TimeFilter(field_name="hora_inicio", lookup_expr="lte")
    precio_max = django_filters.NumberFilter(field_name="precio", lookup_expr="lte")
    estado = django_filters.ChoiceFilter(choices=Turno.Estado.choices, method="filtrar_estado")

    class Meta:
        model = Turno
        fields = ["cancha", "estado"]

    def filtrar_estado(self, queryset, name, value):
        # Para el jugador, un turno bloqueado por un lobby vencido cuenta como LIBRE
        # (ver TurnoSerializer). `liberable` lo anota TurnoViewSet.get_queryset.
        es_staff = self.request is not None and self.request.user.is_staff
        if value == Turno.Estado.LIBRE and not es_staff:
            return queryset.filter(Q(estado=value) | Q(liberable=True))
        if value == Turno.Estado.BLOQUEADO and not es_staff:
            return queryset.filter(estado=value, liberable=False)
        return queryset.filter(estado=value)
