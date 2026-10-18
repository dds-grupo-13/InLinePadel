from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class Conflicto(ValueError):
    """Operación rechazada por estado/concurrencia (HTTP 409)."""


def _respuesta(detalle, codigo):
    return Response({"detail": detalle}, status=codigo)


def manejador_excepciones(exc, context):
    if isinstance(exc, Conflicto):
        return _respuesta(str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, DjangoValidationError):
        datos = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
        return Response(datos, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, ValueError):
        return _respuesta(str(exc), status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, OperationalError):
        # lock_timeout vencido u otra falla de bloqueo
        return _respuesta(
            "El recurso está siendo utilizado por otra operación. Reintentá en unos segundos.",
            status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, IntegrityError):
        return _respuesta(
            "La operación entra en conflicto con datos existentes.",
            status.HTTP_409_CONFLICT,
        )
    return exception_handler(exc, context)
