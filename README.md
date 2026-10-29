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
python manage.py createcachetable
python manage.py seed_demo_data
python manage.py runserver
```

`createcachetable` crea la tabla de la caché compartida que usa el throttling
(límite de intentos de login) cuando hay varios workers.

El comando `seed_demo_data` **reinicia** los datos de la demo: borra partidas,
turnos, contactos, invitaciones y notificaciones (y los clubes, zonas y usuarios
creados a mano) y vuelve a crear zonas, clubes, canchas, la grilla de turnos de
mañana y pasado, las partidas de cada escenario y los usuarios demo. Algunas
partidas dependen de la hora (reserva firme y check-in con el código `CAFE-2026`),
así que conviene correrlo como mucho una hora antes de presentar. Al terminar
imprime los escenarios armados. El despliegue con Docker está en
`../InLinePadel-Interfaz/docker-compose.yml`.

---

## Tests

Suite completa (SQLite, sin dependencias externas):

```bash
USE_SQLITE=1 SECRET_KEY=x python manage.py test
```

### Flujo E2E con Postman / newman

La carpeta **"Flujo E2E"** de `InLinePadel.postman_collection.json` recorre el ciclo
completo contra un server real: registro de jugadores, contactos, cancha y turnos
nuevos (en 3 días, en 2 horas y en 10 minutos), partida completa, bajarse,
reserva firme, cesión del lugar, cancelación por el club, check-in y ocupación.
Es autocontenida: solo necesita el admin de Club Padel Norte que crea el seed.

```bash
python manage.py migrate
python manage.py createcachetable
python manage.py seed_demo_data
python manage.py runserver            # con DEBUG=1 y ALLOWED_HOSTS en el .env
npx newman run InLinePadel.postman_collection.json --folder "Flujo E2E"
```

Usa 6 logins por corrida y el límite es de 10 cada 15 minutos por IP, así que
para repetirla enseguida hay que limpiar el throttling (la caché es compartida,
también entre workers):

```bash
python manage.py shell -c "from django.core.cache import cache; cache.clear()"
```

Las demás carpetas de la colección son requests sueltos de referencia; sus
variables (`username`, `admin_username`, etc.) coinciden con los usuarios del seed.

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

## Reglas de cancelación

El **horario de cierre** es `inicio del turno − 3 h` (`Lobby.HORAS_CIERRE`). Es el
momento en que una reserva confirmada pasa a ser **firme**. Los lobbies exponen
`cierre`, `reserva_firme`, `puede_cancelar`, `puede_abandonar`, `puede_ceder`,
`cesion_pendiente` y `aviso_cierre`: el front se guía por esos campos.

| Situación | Capitán | Cualquier inscripto | Club |
|---|---|---|---|
| **En formación** (reserva provisoria) | Puede cancelar; el turno queda libre | Puede salir. Si sale el capitán, la capitanía pasa al siguiente; si sale el último, se cancela | Puede cancelar con motivo (turno no disponible) |
| **Completa, antes del cierre** | No puede cancelar | Puede bajarse: la partida vuelve a en formación, el código deja de valer, el turno pasa a bloqueado, se avisa a los demás y al club. El plazo reabierto nunca supera el cierre. También puede ceder su lugar | Puede cancelar con motivo |
| **Completa, después del cierre** (firme) | No puede cancelar | No puede bajarse; solo ceder su lugar a un contacto | Puede cancelar con motivo (única vía) |

- **Plazo al crear:** `min(ahora + 48 h, cierre)`. Una partida de último momento
  (creada dentro de la ventana de cierre) tiene plazo hasta el inicio: apenas se
  completa, queda firme.
- **Cancelación por el club:** `POST /api/clubes/turnos/{id}/cancelar_por_club/`
  con `motivo` (5 a 200 caracteres), antes del inicio del turno.
- **Ceder el lugar:** `POST /api/partidas/lobbies/{id}/ceder/` con `receptor` (un
  contacto aceptado). Es una invitación de reemplazo (`tipo: CESION`): al
  aceptarla, el receptor ocupa el mismo cupo y se conserva el código.
- **Dar de baja la cuenta:** se rechaza (409) si el jugador está en una partida
  con reserva firme.
- Cada lobby cancelado guarda `cancelada_por` (`CAPITAN`, `ABANDONO`,
  `VENCIMIENTO`, `CLUB`, `SISTEMA`) y `motivo_cancelacion`.

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
