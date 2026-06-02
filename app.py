#!/usr/bin/env python3
"""
Apple Health Dashboard — punto de entrada.
"""

import os
import secrets
from flask import Flask
from flask_compress import Compress
from pathlib import Path

from routes.main      import main_bp
from routes.importer  import importer_bp
from routes.dashboard import dashboard_bp
from routes.debug     import debug_bp
from routes.ecg       import ecg_bp
from routes.workout   import workout_bp
from routes.history   import history_bp
from routes.auth      import auth_bp, login_manager
from routes.settings   import settings_bp
from routes.health_data import health_data_bp
from routes.wrapped       import wrapped_bp
from routes.gamification  import gami_bp
from flask_login      import login_required


def create_app():
    app = Flask(__name__)
    # Comprimir respuestas con gzip — reduce JS/HTML/JSON 3-5x
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'application/javascript',
        'application/json', 'text/javascript'
    ]
    app.config['COMPRESS_MIN_SIZE'] = 500
    app.config['COMPRESS_LEVEL']    = 6
    Compress(app)

    app.config['UPLOAD_FOLDER']        = Path('uploads')
    app.config['DATA_FOLDER']          = Path('data')
    app.config['MAX_CONTENT_LENGTH']   = 500 * 1024 * 1024  # 500 MB
    # SECRET_KEY persistente — se genera una vez y se guarda en disco
    key_file = Path('data/secret_key.txt')
    if os.environ.get('SECRET_KEY'):
        secret_key = os.environ['SECRET_KEY']
    elif key_file.exists():
        secret_key = key_file.read_text().strip()
    else:
        secret_key = secrets.token_hex(32)
        key_file.parent.mkdir(exist_ok=True)
        key_file.write_text(secret_key)
    app.config['SECRET_KEY'] = secret_key
    app.config['REMEMBER_COOKIE_DURATION'] = 60 * 60 * 24 * 30  # 30 días

    # Comprimir respuestas con gzip — reduce JS/HTML/JSON 3-5x
    app.config['COMPRESS_MIMETYPES'] = [
        'text/html', 'text/css', 'application/javascript',
        'application/json', 'text/javascript'
    ]
    app.config['COMPRESS_MIN_SIZE'] = 500
    app.config['COMPRESS_LEVEL']    = 6
    Compress(app)

    app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)
    app.config['DATA_FOLDER'].mkdir(exist_ok=True)

    # ── Auth ─────────────────────────────────────────────────────────────────
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    app.register_blueprint(auth_bp)

    # ── Blueprints ────────────────────────────────────────────────────────────
    app.register_blueprint(main_bp)
    app.register_blueprint(importer_bp)
    app.register_blueprint(dashboard_bp)

    from services.db import init_db
    with app.app_context():
        init_db()

    # Debug solo si DEBUG=1
    if os.environ.get('DEBUG') == '1':
        app.register_blueprint(debug_bp)
    app.register_blueprint(ecg_bp)
    app.register_blueprint(workout_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(health_data_bp)
    app.register_blueprint(wrapped_bp)
    app.register_blueprint(gami_bp)

    # ── Proteger todas las rutas excepto login/static ─────────────────────────
    @app.before_request
    def require_login():
        from flask import request, redirect, url_for
        from flask_login import current_user
        from routes.auth import must_change_password
        public = {'auth.login', 'auth.logout', 'auth.force_change', 'static', 'main.service_worker'}
        if request.endpoint in public:
            return
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login', next=request.path))
        # Forzar cambio de contraseña si es la primera vez
        if must_change_password() and request.endpoint != 'auth.force_change':
            return redirect(url_for('auth.force_change'))

    from datetime import datetime

    @app.context_processor
    def inject_now():
        return {'now': datetime.now()}

    # Cache de assets estáticos: 7 días en el navegador
    @app.after_request
    def add_cache_headers(response):
        if request_path := getattr(response, '_request_path', None):
            pass
        # Acceder via flask request context
        from flask import request as _req
        try:
            if _req.path.startswith('/static/'):
                response.headers['Cache-Control'] = 'public, max-age=604800'  # 7 días
            elif _req.path.startswith('/api/'):
                response.headers['Cache-Control'] = 'no-store'
        except Exception:
            pass
        return response

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
