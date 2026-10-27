import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


logger = logging.getLogger(__name__)

_SQLSTATE_BLOQUEO = {"55P03", "40001", "40P01"}


# Criterio de códigos HTTP para errores de dominio:
# - Conflicto (409): la operación choca con el estado actual de otro recurso
#   (turno tomado, cupo ocupado, superposición con otra partida, lobby que ya
#   no está abierto).
# - ErrorDominio (400): el pedido es inválido en sí mismo (turno pasado, club
#   o cancha no habilitados, límite de lobbies en formación).
class ErrorDominio(ValueError):
    pass


class Conflicto(ErrorDominio):
    pass


def _es_falla_de_bloqueo(exc):
    sqlstate = getattr(exc.__cause__, "sqlstate", None)
    if sqlstate is not None:
        return sqlstate in _SQLSTATE_BLOQUEO
    return "locked" in str(exc).lower()


def _respuesta(detalle, codigo):
    return Response({"detail": detalle}, status=codigo)


def manejador_excepciones(exc, context):
    if isinstance(exc, Conflicto):
        return _respuesta(str(exc), status.HTTP_409_CONFLICT)
    if isinstance(exc, DjangoValidationError):
        datos = exc.message_dict if hasattr(exc, "error_dict") else exc.messages
        return Response(datos, status=status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, ErrorDominio):
        return _respuesta(str(exc), status.HTTP_400_BAD_REQUEST)
    if isinstance(exc, OperationalError) and _es_falla_de_bloqueo(exc):
        logger.warning("Falla de bloqueo en la base", exc_info=exc)
        return _respuesta(
            "El recurso está siendo utilizado por otra operación. Reintentá en unos segundos.",
            status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, IntegrityError):
        logger.warning("Conflicto de integridad", exc_info=exc)
        return _respuesta(
            "La operación entra en conflicto con datos existentes.",
            status.HTTP_409_CONFLICT,
        )
    return exception_handler(exc, context)
