import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, OperationalError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


logger = logging.getLogger(__name__)

# SQLSTATE de Postgres: lock_not_available (lock_timeout), serialization_failure, deadlock_detected
_SQLSTATE_BLOQUEO = {"55P03", "40001", "40P01"}


class ErrorDominio(ValueError):
    """Regla de negocio incumplida por el pedido (HTTP 400).

    Un ValueError "pelado" ya no se traduce a 400: sería un bug y debe verse como 500.
    """


class Conflicto(ErrorDominio):
    """Operación rechazada por estado/concurrencia (HTTP 409)."""


def _es_falla_de_bloqueo(exc):
    sqlstate = getattr(exc.__cause__, "sqlstate", None)
    if sqlstate is not None:
        return sqlstate in _SQLSTATE_BLOQUEO
    return "locked" in str(exc).lower()  # SQLite: "database is locked"


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
        # lock_timeout vencido, deadlock o falla de serialización; el resto
        # (base caída, etc.) sigue de largo y termina en un 500 logueado
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
