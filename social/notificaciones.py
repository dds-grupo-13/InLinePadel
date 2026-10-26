from .models import Notificacion


def notificar(usuarios, mensaje):
    ids = {u.pk if hasattr(u, "pk") else u for u in usuarios}
    Notificacion.objects.bulk_create(
        [Notificacion(usuario_id=pk, mensaje=mensaje) for pk in ids]
    )
