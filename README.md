# Guía de trabajo del proyecto

## Antes de empezar a escribir código

Antes de realizar cambios en el código:

1. Crear una nueva branch de Git:

```bash
git checkout -b nombre-de-la-rama
```

2. Subir el código a la rama siguiendo el flujo normal:

```bash
git add .
git commit -m "Descripción de los cambios"
```

3. Empujar la rama al repositorio remoto:

```bash
git push origin nombre-de-la-rama
```

Cuando estemos seguros de que funca, hacer un **Pull Request (PR)** y enviarlo a `main`.

---

## Para correr el proyecto

Ejecutar los siguientes pasos:

1. Crear el entorno virtual:

```bash
python -m venv venv
```

2. Activar el entorno virtual:

Windows (PowerShell):

```powershell
.\venv\Scripts\Activate.ps1
```

Linux / macOS:

```bash
source venv/bin/activate
```

3. Instalar las dependencias:

```bash
pip install -r requirements.txt
```

4. Configurar la base de datos en el `.env` (copiar de `.env.example`) y
   aplicar migraciones + datos demo. Para desarrollo local el `.env` tiene que
   incluir `DEBUG=1` y `ALLOWED_HOSTS=localhost,127.0.0.1`: sin `DEBUG` el
   default es `0` (producción) y el servidor rechaza los hosts no listados.

```bash
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

El comando `seed_demo_data` es idempotente: crea zonas, clubes, canchas,
turnos, partidas y los usuarios demo para la presentación. El despliegue con
Docker está en `../InLinePadel-Interfaz/docker-compose.yml`.

---

## Tests

Suite completa (SQLite, sin dependencias externas):

```bash
USE_SQLITE=1 SECRET_KEY=x python manage.py test
```

### Concurrencia contra PostgreSQL (RNF02)

`partidas/test_concurrencia.py` valida el anti-overbooking con hilos reales
(50 solicitudes sobre el último cupo, 20 capitanes sobre el mismo turno,
cancelar contra ocupar el último cupo). SQLite no puede validarlo, así que
esos tests se saltean salvo que la base sea PostgreSQL. El `db` del
docker-compose no publica el puerto; una forma de correrlo:

```bash
docker run --rm -d --name pg-test -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres postgres:17
```

Con un `.env` que apunte a esa base (`DB_NAME=postgres`, `DB_USER=postgres`,
`DB_PASSWORD=postgres`, `DB_HOST=localhost`, `DB_PORT=5432`):

```bash
python manage.py test partidas.test_concurrencia
```

---

## Autenticación (JWT) y CORS

Variable de entorno (ver `.env.example`): `CORS_ALLOWED_ORIGINS`, orígenes del frontend separados por coma (por defecto `http://localhost:4200`).

Endpoints en `/api/usuarios/auth/`:

| Endpoint | Body | Respuesta |
|---|---|---|
| `POST login/` | `username`, `password` | `access`, `refresh`, `usuario` |
| `POST refresh/` | `refresh` | nuevo `access` y nuevo `refresh` (401 si es inválido o ya usado) |
| `POST logout/` (con Bearer) | `refresh` | 204; el refresh queda invalidado |

Las demás requests llevan `Authorization: Bearer <access>`. El access dura 15 minutos y el refresh 1 día; el refresh rota en cada uso y el anterior queda en la blacklist. Dar de baja una cuenta invalida todos sus refresh.

---

## Cambios en `models.py`

Si se realizan cambios en los archivos `models.py`, ejecutar:

1. Crear las migraciones:

```bash
python manage.py makemigrations
```

2. Aplicar las migraciones:

```bash
python manage.py migrate
```
