# Turnex — turnera online multiempresa

Aplicación Flask para que negocios de Argentina publiquen su agenda y sus
clientes reserven turnos desde un link propio (`/<slug>`).

- **Plataforma** (`/platform/login`): alta de empresas, planes y pagos.
- **Panel de la empresa** (`/admin/login`): agenda, clientes, prestaciones,
  profesionales, horarios, bloqueos, pagos, equipo e integraciones.
- **Clientes** (`/<slug>`): reservan como invitados o con cuenta, y cancelan o
  reprograman desde el link que reciben por mail.

La app funciona solo en hora de Argentina (`America/Argentina/Buenos_Aires`).

---

## Ejecutar en local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 run.py
```

Con la base vacía se crean datos de demo:

| Qué | Dónde | Usuario |
|---|---|---|
| Página pública | http://127.0.0.1:5000/pepito | — |
| Panel empresa | http://127.0.0.1:5000/admin/login | `admin@pepito.com` / `admin123` |
| Cliente demo | http://127.0.0.1:5000/pepito/customer/login | `lucia@demo.com` / `cliente123` |
| Plataforma | http://127.0.0.1:5000/platform/login | ver abajo |

El usuario de plataforma se crea con `PLATFORM_ADMIN_EMAIL` y
`PLATFORM_ADMIN_PASSWORD`. Si no están definidas, se usa `owner@turnex.com` con
una contraseña al azar que se imprime **una sola vez** en el log de arranque.

> ⚠️ La empresa demo `pepito` (con `admin123`) se crea en **cualquier** base
> vacía, también en producción. Después del primer deploy, desactivala o
> cambiale la contraseña desde plataforma.

---

## Variables de entorno

| Variable | Obligatoria | Para qué |
|---|---|---|
| `FLASK_ENV` | Sí, en producción: `production` | Activa cookies seguras, HTTPS, confianza en el proxy y exige `SECRET_KEY`. |
| `SECRET_KEY` | Sí, en producción | Firma de sesiones. Generala con `python3 -c "import secrets; print(secrets.token_hex(32))"`. |
| `DATABASE_URL` | Sí, en producción | Postgres (`postgres://…` o `postgresql://…`). Sin ella usa SQLite en `instance/turnex.db`. |
| `PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD` | Recomendadas | Usuario de plataforma inicial (solo se usa si todavía no existe ninguno). |
| `MAIL_USERNAME` / `MAIL_PASSWORD` | Para enviar mails | Sin `MAIL_USERNAME` **no sale ningún mail**: solo se escriben en el log. |
| `MAIL_SERVER` / `MAIL_PORT` / `MAIL_USE_TLS` | Según el proveedor | Por defecto `smtp.gmail.com`, `587`, `true`. |
| `MAIL_DEFAULT_SENDER` | Recomendada | Remitente, ej. `Turnex <turnos@tudominio.com>`. |
| `CRON_SECRET` | Para recordatorios | Token del endpoint de recordatorios (ver abajo). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Para Google Calendar | Credenciales OAuth (ver abajo). |
| `GOOGLE_REDIRECT_URI` | Opcional | Fija la URL de retorno de Google. Por defecto `https://<tu-dominio>/admin/integrations/google/callback`. |
| `TRUSTED_PROXIES` | Opcional | Cantidad de proxies delante de la app. Por defecto `1` en producción (Railway/Render) y `0` en local. |

---

## Mails

La app manda mails de confirmación, cancelación, reprogramación,
recordatorio, recuperación de contraseña, bienvenida y aviso de fin de prueba.
Se envían en segundo plano: si el servidor de mail falla o tarda, la reserva no
se ve afectada y el error queda en el log.

Si en producción falta `MAIL_USERNAME`, al arrancar aparece en el log:
`MAIL_USERNAME no está configurado: NO se envían mails`.

Opciones de proveedor (todas por SMTP, puerto 587 con TLS):

| Proveedor | `MAIL_SERVER` | `MAIL_USERNAME` | `MAIL_PASSWORD` |
|---|---|---|---|
| Brevo (plan gratis) | `smtp-relay.brevo.com` | tu login SMTP de Brevo | tu clave SMTP |
| Resend (plan gratis) | `smtp.resend.com` | `resend` | tu API key |
| Gmail (solo para probar) | `smtp.gmail.com` | tu cuenta de Gmail | una *contraseña de aplicación* (requiere verificación en 2 pasos) |

Gmail tiene un límite de unos 500 mails por día y sus envíos suelen caer en
spam. Para producción conviene Brevo o Resend con **tu dominio verificado** y
`MAIL_DEFAULT_SENDER` con una dirección de ese dominio.

---

## Google Calendar

Sincroniza los turnos de un negocio con su Google Calendar: se crean, mueven y
borran eventos automáticamente. La API de Google Calendar es gratuita.

### 1. Configurar Google Cloud (una sola vez, para toda la plataforma)

1. Entrá a <https://console.cloud.google.com> y creá un proyecto (ej. "Turnex").
2. **APIs y servicios → Biblioteca** → buscá **Google Calendar API** → **Habilitar**.
3. **Pantalla de consentimiento de OAuth**:
   - Tipo de usuario: **Externo**.
   - Nombre de la app, email de soporte y dominio de tu sitio (también la URL
     de `/privacidad` y `/terminos`).
   - Permisos (scopes): agregá `https://www.googleapis.com/auth/calendar.events`.
   - Mientras esté en modo **Prueba**, agregá como *usuarios de prueba* los
     Gmail de los negocios que se van a conectar.
4. **Credenciales → Crear credenciales → ID de cliente de OAuth**:
   - Tipo: **Aplicación web**.
   - *URI de redireccionamiento autorizados*: agregá **una sola** URL:
     `https://<tu-dominio>/admin/integrations/google/callback`
     (es la misma para todos los negocios).
5. Copiá el *ID de cliente* y el *Secreto* en `GOOGLE_CLIENT_ID` y
   `GOOGLE_CLIENT_SECRET` y redeployá.

> **Modo Prueba vs. producción:** en modo Prueba solo pueden conectarse hasta
> 100 usuarios de prueba y **la conexión se corta a los 7 días** (hay que volver
> a conectar). Para uso real, en la pantalla de consentimiento elegí
> **Publicar app** y completá la verificación de Google (gratis, pero tarda
> días o semanas porque `calendar.events` es un permiso sensible).

### 2. Habilitarlo para un negocio

Google Calendar está disponible para negocios con plan **PRO** o **PREMIUM** y
estado **ACTIVE**. Cuando un negocio paga, desde **Plataforma** cambiale el plan
y el estado. Después, el dueño entra a **Panel → Integraciones → Google Calendar
→ Conectar** y autoriza con su cuenta de Google.

Si Google falla o tarda, la reserva sigue funcionando: el error queda en el log
con el texto `Google Calendar: no se pudo …`.

---

## Recordatorios automáticos

Se envía un recordatorio 24 horas antes de cada turno. Configurá `CRON_SECRET`
y un cron que llame **cada hora** al endpoint:

```bash
# token por cabecera (recomendado: no queda en los logs de URLs)
curl -s -X POST -H "X-Cron-Token: $CRON_SECRET" https://tu-dominio/internal/cron/reminders

# o por query string
curl -s -X POST "https://tu-dominio/internal/cron/reminders?token=$CRON_SECRET"
```

- En **Railway**: Settings → Cron Jobs → `0 * * * *`.
- En **Render**: Cron Jobs, con el mismo comando.

Busca turnos activos que empiezan dentro de 23 a 25 horas (hora de Argentina),
les manda el mail si hay email y los marca para no repetir. Devuelve un JSON con
`sent`, `skipped` y `errors`. `/internal/cron/health` responde sin token.

---

## Notas de despliegue

- Detrás del proxy de Railway/Render la app necesita `FLASK_ENV=production`
  para reconocer HTTPS. Sin eso, la conexión con Google Calendar falla y los
  links de los mails salen con `http://`.
- Al arrancar se crea un índice único que impide dos turnos activos del mismo
  profesional a la misma hora. Si ya existen turnos duplicados, el log lo avisa
  (`No se pudo crear el índice uq_appointment_employee_start_booked`): resolvé
  esos turnos y reiniciá.
- Los cambios de esquema en SQLite se aplican solos al arrancar. En Postgres,
  cualquier cambio futuro de modelos necesita una migración (Alembic).
