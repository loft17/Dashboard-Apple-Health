#!/usr/bin/env python3
"""
Apple Health Dashboard — punto de entrada.
Solo inicializa Flask y registra los blueprints.
"""

from flask import Flask
from pathlib import Path

from routes.main      import main_bp
from routes.importer  import importer_bp
from routes.dashboard import dashboard_bp
from routes.debug    import debug_bp
from routes.ecg      import ecg_bp
from routes.workout   import workout_bp
from routes.history   import history_bp


def create_app():
    app = Flask(__name__)
    app.config['UPLOAD_FOLDER'] = Path('uploads')
    app.config['DATA_FOLDER']   = Path('data')
    app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

    app.config['UPLOAD_FOLDER'].mkdir(exist_ok=True)
    app.config['DATA_FOLDER'].mkdir(exist_ok=True)

    app.register_blueprint(main_bp)
    app.register_blueprint(importer_bp)
    app.register_blueprint(dashboard_bp)

    # Crear tablas si no existen (seguro llamarlo siempre)
    from services.db import init_db
    with app.app_context():
        init_db()
    app.register_blueprint(debug_bp)
    app.register_blueprint(ecg_bp)
    app.register_blueprint(workout_bp)
    app.register_blueprint(history_bp)

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
