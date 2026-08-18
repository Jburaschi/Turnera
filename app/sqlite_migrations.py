from __future__ import annotations

from sqlalchemy import text


def _table_exists(engine, table_name: str) -> bool:
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table_name},
        ).fetchone()
        return bool(row)


def _column_exists(engine, table_name: str, column_name: str) -> bool:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return any(r[1] == column_name for r in rows)


def _add_column(engine, table_name: str, ddl: str) -> None:
    # ddl example: "manage_token VARCHAR(64)"
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {ddl}"))


def run_sqlite_migrations(engine) -> None:
    """Evoluciona el esquema de una base SQLite existente (agrega columnas/tablas
    nuevas sin borrar datos). Solo corre sobre SQLite: en Postgres, la primera vez
    `db.create_all()` ya crea el esquema completo y correcto; para cambios de
    esquema DESPUÉS de tener datos reales en Postgres hace falta una migración
    real (Alembic/Flask-Migrate), no este script."""
    if engine.dialect.name != 'sqlite':
        return

    # appointment: google_event_id, manage_token
    if _table_exists(engine, "appointment"):
        if not _column_exists(engine, "appointment", "google_event_id"):
            _add_column(engine, "appointment", "google_event_id VARCHAR(255)")
        if not _column_exists(engine, "appointment", "manage_token"):
            _add_column(engine, "appointment", "manage_token VARCHAR(64)")

    # customer: tags, notes, needs_password_setup
    if _table_exists(engine, "customer"):
        if not _column_exists(engine, "customer", "tags"):
            _add_column(engine, "customer", "tags VARCHAR(255)")
        if not _column_exists(engine, "customer", "notes"):
            _add_column(engine, "customer", "notes TEXT")
        if not _column_exists(engine, "customer", "needs_password_setup"):
            _add_column(engine, "customer", "needs_password_setup BOOLEAN DEFAULT 0 NOT NULL")
        if not _column_exists(engine, "customer", "birth_date"):
            _add_column(engine, "customer", "birth_date DATE")

    if not _table_exists(engine, "employee_schedule_service"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE employee_schedule_service (
                        schedule_id INTEGER NOT NULL,
                        service_id INTEGER NOT NULL,
                        PRIMARY KEY (schedule_id, service_id),
                        FOREIGN KEY(schedule_id) REFERENCES employee_schedule(id) ON DELETE CASCADE,
                        FOREIGN KEY(service_id) REFERENCES service(id)
                    )
                    """
                )
            )

    # google_calendar_connection table
    if not _table_exists(engine, "google_calendar_connection"):
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE google_calendar_connection (
                        id INTEGER PRIMARY KEY,
                        company_id INTEGER NOT NULL UNIQUE,
                        admin_user_id INTEGER,
                        enabled BOOLEAN NOT NULL DEFAULT 1,
                        calendar_id VARCHAR(255) NOT NULL DEFAULT 'primary',
                        refresh_token TEXT,
                        access_token TEXT,
                        token_expiry DATETIME,
                        scopes TEXT,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        FOREIGN KEY(company_id) REFERENCES company(id),
                        FOREIGN KEY(admin_user_id) REFERENCES admin_user(id)
                    )
                    """
                )
            )

    # company: trial_expires_at, trial_warning_sent
    if _table_exists(engine, "company"):
        if not _column_exists(engine, "company", "trial_expires_at"):
            _add_column(engine, "company", "trial_expires_at DATETIME")
        if not _column_exists(engine, "company", "trial_warning_sent"):
            _add_column(engine, "company", "trial_warning_sent BOOLEAN NOT NULL DEFAULT 0")

    # appointment: reminder_sent
    if _table_exists(engine, "appointment"):
        if not _column_exists(engine, "appointment", "reminder_sent"):
            _add_column(engine, "appointment", "reminder_sent BOOLEAN NOT NULL DEFAULT 0")

    # company: cancelation fields (legacy "NUEVO")
    if _table_exists(engine, "company"):
        for col, typedef in [
            ("cancelation_limit_hours",     "INTEGER NOT NULL DEFAULT 24"),
            ("cancelation_penalty_enabled", "BOOLEAN NOT NULL DEFAULT 0"),
            ("cancelation_penalty_amount",  "FLOAT NOT NULL DEFAULT 0"),
            ("timezone",                    "VARCHAR(80) NOT NULL DEFAULT 'America/Argentina/Buenos_Aires'"),
        ]:
            if not _column_exists(engine, "company", col):
                _add_column(engine, "company", f"{col} {typedef}")

    # appointment: legacy "NUEVO" fields
    if _table_exists(engine, "appointment"):
        for col, typedef in [
            ("canceled_at",          "DATETIME"),
            ("rescheduled_from_id",  "INTEGER"),
            ("penalty_applied",      "BOOLEAN NOT NULL DEFAULT 0"),
            ("google_event_id",      "VARCHAR(255)"),
            ("manage_token",         "VARCHAR(64)"),
        ]:
            if not _column_exists(engine, "appointment", col):
                _add_column(engine, "appointment", f"{col} {typedef}")

    # employee: photo_url, bio
    if _table_exists(engine, "employee"):
        if not _column_exists(engine, "employee", "photo_url"):
            _add_column(engine, "employee", "photo_url VARCHAR(500)")
        if not _column_exists(engine, "employee", "bio"):
            _add_column(engine, "employee", "bio VARCHAR(300)")

    # admin_user: role
    if _table_exists(engine, "admin_user"):
        if not _column_exists(engine, "admin_user", "role"):
            _add_column(engine, "admin_user", "role VARCHAR(20) NOT NULL DEFAULT 'admin'")

    # appointment_log table
    if not _table_exists(engine, "appointment_log"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE appointment_log (
                    id INTEGER PRIMARY KEY,
                    appointment_id INTEGER NOT NULL REFERENCES appointment(id),
                    action VARCHAR(30) NOT NULL,
                    old_value VARCHAR(100),
                    new_value VARCHAR(100),
                    actor_type VARCHAR(20),
                    actor_id INTEGER,
                    actor_name VARCHAR(120),
                    notes VARCHAR(255),
                    created_at DATETIME NOT NULL
                )
            """))

    # admin_user: reset_token, reset_token_expires
    if _table_exists(engine, "admin_user"):
        if not _column_exists(engine, "admin_user", "reset_token"):
            _add_column(engine, "admin_user", "reset_token VARCHAR(100)")
        if not _column_exists(engine, "admin_user", "reset_token_expires"):
            _add_column(engine, "admin_user", "reset_token_expires DATETIME")

    # customer: reset_token, reset_token_expires
    if _table_exists(engine, "customer"):
        if not _column_exists(engine, "customer", "reset_token"):
            _add_column(engine, "customer", "reset_token VARCHAR(100)")
        if not _column_exists(engine, "customer", "reset_token_expires"):
            _add_column(engine, "customer", "reset_token_expires DATETIME")
        if not _column_exists(engine, "customer", "created_at"):
            _add_column(engine, "customer", "created_at DATETIME")
            with engine.begin() as conn:
                conn.execute(text("UPDATE customer SET created_at = COALESCE(created_at, CURRENT_TIMESTAMP) WHERE created_at IS NULL"))

    # company: category, onboarding_step (wizard de alta)
    if _table_exists(engine, "company"):
        if not _column_exists(engine, "company", "category"):
            _add_column(engine, "company", "category VARCHAR(80)")
        if not _column_exists(engine, "company", "onboarding_step"):
            _add_column(engine, "company", "onboarding_step INTEGER NOT NULL DEFAULT 1")
        if not _column_exists(engine, "company", "staffing_mode"):
            _add_column(engine, "company", "staffing_mode VARCHAR(20)")

    if _table_exists(engine, "blocked_period"):
        if not _column_exists(engine, "blocked_period", "block_type"):
            _add_column(engine, "blocked_period", "block_type VARCHAR(20) NOT NULL DEFAULT 'manual'")

    if _table_exists(engine, "appointment"):
        for col, ddl in [
            ("payment_status", "payment_status VARCHAR(20)"),
            ("payment_method", "payment_method VARCHAR(40)"),
            ("paid_amount", "paid_amount NUMERIC(10,2)"),
            ("payment_notes", "payment_notes VARCHAR(255)"),
        ]:
            if not _column_exists(engine, "appointment", col):
                _add_column(engine, "appointment", ddl)

    if _table_exists(engine, "service"):
        if not _column_exists(engine, "service", "color"):
            _add_column(engine, "service", "color VARCHAR(20)")
        if not _column_exists(engine, "service", "photo_url"):
            _add_column(engine, "service", "photo_url VARCHAR(500)")

    if _table_exists(engine, "company"):
        if not _column_exists(engine, "company", "instagram_url"):
            _add_column(engine, "company", "instagram_url VARCHAR(255)")
        if not _column_exists(engine, "company", "facebook_url"):
            _add_column(engine, "company", "facebook_url VARCHAR(255)")
        if not _column_exists(engine, "company", "cover_photo_url"):
            _add_column(engine, "company", "cover_photo_url VARCHAR(500)")

    # company_hours table (horarios de atención a nivel negocio)
    if not _table_exists(engine, "company_hours"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE company_hours (
                    id INTEGER PRIMARY KEY,
                    company_id INTEGER NOT NULL REFERENCES company(id),
                    weekday INTEGER NOT NULL,
                    start_time TIME NOT NULL,
                    end_time TIME NOT NULL
                )
            """))

    # slot_hold table (reserva temporal de horario mientras el cliente completa el form)
    if not _table_exists(engine, "slot_hold"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE slot_hold (
                    id INTEGER PRIMARY KEY,
                    company_id INTEGER NOT NULL REFERENCES company(id),
                    employee_id INTEGER NOT NULL REFERENCES employee(id),
                    start_dt DATETIME NOT NULL,
                    end_dt DATETIME NOT NULL,
                    session_key VARCHAR(64) NOT NULL,
                    expires_at DATETIME NOT NULL
                )
            """))
            conn.execute(text("CREATE INDEX ix_slot_hold_start_dt ON slot_hold (start_dt)"))
            conn.execute(text("CREATE INDEX ix_slot_hold_expires_at ON slot_hold (expires_at)"))

    # uploaded_image table (logos/fotos guardados como bytes en la propia base)
    if not _table_exists(engine, "uploaded_image"):
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE uploaded_image (
                    id INTEGER PRIMARY KEY,
                    company_id INTEGER NOT NULL REFERENCES company(id),
                    mime_type VARCHAR(50) NOT NULL,
                    data BLOB NOT NULL,
                    created_at DATETIME NOT NULL
                )
            """))
            conn.execute(text("CREATE INDEX ix_uploaded_image_company_id ON uploaded_image (company_id)"))

    # company_config: qué datos de contacto se muestran en la página pública
    if _table_exists(engine, "company_config"):
        for col in ("show_address_public", "show_phone_public", "show_email_public"):
            if not _column_exists(engine, "company_config", col):
                _add_column(engine, "company_config", f"{col} BOOLEAN NOT NULL DEFAULT 1")
