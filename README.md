# Turnera SaaS mejorada

Proyecto Flask para una turnera multiempresa donde:

- cada empresa tiene su URL pública propia (`/<slug>`)
- la experiencia del cliente quedó intacta
- se agregó un panel de plataforma para dar de alta empresas, slugs y usuarios admin
- se reforzó el panel empresa para operar agenda, clientes, prestaciones, profesionales y bloqueos

## Qué cambió

### Plataforma

- login de plataforma independiente
- alta de empresa con:
  - nombre
  - slug/url
  - admin inicial
  - plan
  - estado
- edición posterior de empresa y admin
- registro de pagos por empresa

### Panel empresa

- agenda con filtros
- alta manual de turnos
- cambio de estado del turno (`BOOKED`, `DONE`, `NO_SHOW`, `CANCELED`)
- reprogramación de turnos
- CRUD de clientes
- CRUD de prestaciones
- CRUD de profesionales
- edición completa de horarios por profesional
- bloqueos de agenda por empresa o por profesional

### Backend

- validaciones básicas de formularios
- validación de que un profesional realmente haga la prestación reservada
- corrección del conteo mensual de turnos
- soporte para usuarios de plataforma
- soporte para empresas activas/inactivas y planes
- soporte para bloqueos que impactan la disponibilidad

## Ejecutar

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 run.py
```

## URLs demo

### Cliente

- `http://127.0.0.1:5000/pepito`

### Login empresa

- `http://127.0.0.1:5000/admin/login`

### Login plataforma

- `http://127.0.0.1:5000/platform/login`

## Credenciales demo

### Plataforma

- email: `owner@turnera.com`
- password: `owner123`

### Empresa demo

- slug: `pepito`
- email: `admin@pepito.com`
- password: `admin123`

### Cliente demo

- empresa: `pepito`
- email: `lucia@demo.com`
- password: `cliente123`

## Nota

El zip se entrega sin la base SQLite generada para que al iniciar cree una base nueva con el esquema actualizado.

## Recordatorios automáticos de turno

Turnex usa un endpoint de cron para enviar recordatorios 24 horas antes de cada turno.

### Configuración

1. Generá un token secreto:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. Agregalo como variable de entorno `CRON_SECRET`.

3. Configurá un cron job que llame al endpoint **cada hora**:

   ```bash
   # crontab (Linux/Mac)
   0 * * * * curl -s -X POST "https://tu-dominio.com/internal/cron/reminders?token=TU_SECRET"
   ```

   En **Railway**: Settings → Cron Jobs → `0 * * * *` → command: `curl -X POST https://tu-app.railway.app/internal/cron/reminders?token=$CRON_SECRET`

   En **Render**: usa Cron Jobs en el dashboard con la misma URL.

### Comportamiento

- Busca turnos `BOOKED` que empiezan entre 23 y 25 horas desde el momento de la llamada
- Solo manda si el turno tiene email (cliente registrado o invitado con email)
- Marca `reminder_sent = True` para no volver a mandar
- Devuelve JSON con `sent`, `skipped` y `errors`
- El endpoint `/internal/cron/health` responde sin token para verificar que la app está viva

### Sin cron configurado

Sin `CRON_SECRET` el endpoint devuelve 403. En desarrollo podés probarlo manualmente:

```bash
# Setear la variable
export CRON_SECRET=mi-token-local

# Llamar el endpoint
curl -X POST "http://localhost:5000/internal/cron/reminders?token=mi-token-local"
```
