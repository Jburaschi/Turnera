import os
from flask import Flask, render_template
from .extensions import db, login_manager, csrf, limiter, mail
from .models import AdminUser, Customer, PlatformUser
from .blueprints.public import public_bp
from .blueprints.admin import admin_bp
from .blueprints.auth import auth_bp
from .blueprints.platform import platform_bp
from .blueprints.onboarding import onboarding_bp
from .blueprints.cron import cron_bp
from .blueprints.media import media_bp
from .seed import seed_if_empty
from .sqlite_migrations import run_sqlite_migrations


def create_app():
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    # ── Configuracion core ──────────────────────────────────────────────────
    is_production = os.getenv('FLASK_ENV', '').lower() == 'production'

    secret = os.getenv('SECRET_KEY')
    if not secret:
        if is_production:
            raise RuntimeError(
                'SECRET_KEY no está configurada. Es obligatoria en producción '
                '(FLASK_ENV=production) — generá una con: '
                'python3 -c "import secrets; print(secrets.token_hex(32))"'
            )
        import warnings
        warnings.warn(
            'SECRET_KEY no configurada. Usando clave de desarrollo — NO apta para produccion.',
            stacklevel=2,
        )
        secret = 'dev-secret-CHANGE-ME-in-production'

    app.config['SECRET_KEY'] = secret
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600

    # ── Cookies de sesión ────────────────────────────────────────────────────
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = is_production
    app.config['REMEMBER_COOKIE_HTTPONLY'] = True
    app.config['REMEMBER_COOKIE_SAMESITE'] = 'Lax'
    app.config['REMEMBER_COOKIE_SECURE'] = is_production

    # Límite duro de tamaño de request (protege contra DoS por uploads gigantes,
    # más allá del chequeo de 2MB que hacemos a mano en cada endpoint de imagen)
    app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # 8MB

    # ── Base de datos ───────────────────────────────────────────────────────
    db_url = os.getenv('DATABASE_URL', 'sqlite:///' + os.path.join(app.instance_path, 'turnex.db'))
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql+psycopg://', 1)
    elif db_url.startswith('postgresql://'):
        db_url = db_url.replace('postgresql://', 'postgresql+psycopg://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # ── Email (Flask-Mail) ──────────────────────────────────────────────────
    app.config['MAIL_SERVER']          = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT']            = int(os.getenv('MAIL_PORT', '587'))
    app.config['MAIL_USE_TLS']         = os.getenv('MAIL_USE_TLS', 'true').lower() == 'true'
    app.config['MAIL_USERNAME']        = os.getenv('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD']        = os.getenv('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER']  = os.getenv('MAIL_DEFAULT_SENDER', os.getenv('MAIL_USERNAME', 'noreply@turnex.com'))

    # ── Extensiones ─────────────────────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.customer_login'
    csrf.init_app(app)
    limiter.init_app(app)
    mail.init_app(app)

    @login_manager.user_loader
    def load_user(user_id: str):
        if user_id.startswith('platform:'):
            return PlatformUser.query.get(int(user_id.split(':', 1)[1]))
        if user_id.startswith('admin:'):
            return AdminUser.query.get(int(user_id.split(':', 1)[1]))
        if user_id.startswith('customer:'):
            return Customer.query.get(int(user_id.split(':', 1)[1]))
        return None

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(public_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(platform_bp)
    app.register_blueprint(onboarding_bp)
    app.register_blueprint(cron_bp)
    app.register_blueprint(media_bp)

    # ── Cabeceras de seguridad HTTP ──────────────────────────────────────────
    @app.after_request
    def set_security_headers(response):
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdn.jsdelivr.net; "
            "img-src 'self' data: https:; "
            "font-src 'self' data:; "
            "frame-ancestors 'none'; "
            "object-src 'none'; "
            "base-uri 'self'"
        )
        if is_production:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    # ── Manejadores de error ──────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        return render_template('errors/404.html'), 404

    @app.errorhandler(403)
    def forbidden(e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(429)
    def rate_limited(e):
        return render_template('errors/429.html'), 429

    @app.errorhandler(500)
    def server_error(e):
        return render_template('errors/500.html'), 500

    # ── DB y seed ─────────────────────────────────────────────────────────────
    with app.app_context():
        db.create_all()
        try:
            run_sqlite_migrations(db.engine)
        except Exception as e:
            print(f'⚠ Error corriendo migraciones: {e}')
        seed_if_empty()

    return app
