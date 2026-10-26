import django_filters

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

    class Meta:
        model = Turno
        fields = ["cancha", "estado"]
