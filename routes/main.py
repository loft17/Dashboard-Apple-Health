"""
routes/main.py
Blueprint para la página de inicio y la subida del ZIP.
"""

import threading
from pathlib import Path
from flask_login import login_required

from flask import Blueprint, current_app, jsonify, render_template, request, Response, stream_with_context
import json, queue, time

from services.db       import load_stats
from services.importer import import_state, process_zip, progress_queue

main_bp = Blueprint('main', __name__)


@main_bp.route('/api/types')
@login_required
def api_types():
    """Lista todos los tipos de datos en la BD — útil para configuración."""
    from flask import jsonify
    from flask_login import login_required as _lr
    from services.db import get_conn, DB_FILE
    if not DB_FILE.exists():
        return jsonify([])
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT type, COUNT(*) as n, MIN(date_day) as first, MAX(date_day) as last "
            "FROM records GROUP BY type ORDER BY n DESC"
        ).fetchall()
    return jsonify([dict(r) for r in rows])


@main_bp.route('/sw.js')
def service_worker():
    from flask import send_from_directory, current_app
    import os
    static_dir = os.path.join(current_app.root_path, 'static')
    resp = send_from_directory(static_dir, 'sw.js',
                               mimetype='application/javascript')
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@main_bp.route('/')
def index():
    from flask import redirect
    from services.db import DB_FILE, get_available_dates
    if not DB_FILE.exists():
        return redirect('/ajustes')
    # Comprobar si hay datos
    try:
        dates = get_available_dates()
        if not dates:
            return redirect('/ajustes')
    except Exception:
        return redirect('/ajustes')
    return redirect('/dashboard')


@main_bp.route('/upload', methods=['POST'])
def upload():
    if import_state['running']:
        return jsonify({'error': 'Ya hay una importación en curso'}), 409

    if 'file' not in request.files:
        return jsonify({'error': 'No se encontró el archivo'}), 400

    file = request.files['file']
    if not file.filename.endswith('.zip'):
        return jsonify({'error': 'Solo se aceptan archivos .zip'}), 400

    zip_path: Path = current_app.config['UPLOAD_FOLDER'] / 'export.zip'
    file.save(zip_path)
    size_mb = round(zip_path.stat().st_size / 1024 / 1024, 1)

    threading.Thread(target=process_zip, args=(zip_path,), daemon=True).start()

    return jsonify({'success': True, 'size_mb': size_mb})


@main_bp.route('/progress-stream')
def progress_stream():
    """SSE: el frontend se suscribe aquí para recibir el progreso de la importación."""
    def generate():
        yield 'data: {"event":"connected"}\n\n'
        start = time.time()
        while True:
            if time.time() - start > 600:
                yield 'data: {"event":"timeout"}\n\n'
                break
            try:
                item = progress_queue.get(timeout=1)
                payload = json.dumps({'event': item['event'], **item['data']})
                yield f'data: {payload}\n\n'
                if item['event'] in ('done', 'error'):
                    try:
                        from routes.dashboard import invalidate_cache
                        from routes.history import invalidate_hist_cache
                        invalidate_cache()
                        invalidate_hist_cache()
                    except Exception:
                        pass
                    break
            except queue.Empty:
                yield ': heartbeat\n\n'

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@main_bp.route('/import-status')
def import_status():
    return jsonify(import_state)


@main_bp.route('/status')
def status():
    stats = load_stats()
    return jsonify(stats or {'status': 'empty'})


@main_bp.route('/api/debug/mindful')
@login_required
def debug_mindful():
    """Diagnóstico de sesiones de mindfulness."""
    from services.db import get_conn, DB_FILE
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT type, date_day, start_date, end_date, value, value_str "
            "FROM records WHERE type LIKE '%Mindful%' OR type LIKE '%mindful%' "
            "ORDER BY start_date DESC LIMIT 10"
        ).fetchall()
        count = conn.execute(
            "SELECT COUNT(*) FROM records WHERE type LIKE '%Mindful%'"
        ).fetchone()[0]
    return jsonify({
        'total': count,
        'records': [dict(r) for r in rows]
    })


@main_bp.route('/api/debug/mood-types')
@login_required  
def debug_mood_types():
    """Busca todos los tipos relacionados con ánimo, bienestar y salud mental."""
    from services.db import get_conn, DB_FILE
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT type, COUNT(*) as n, MIN(date_day) as first, MAX(date_day) as last,
                   MIN(value_str) as sample_str, MIN(CAST(value AS TEXT)) as sample_val
            FROM records 
            WHERE type LIKE '%Mind%' OR type LIKE '%Mood%' OR type LIKE '%State%'
               OR type LIKE '%Anxiety%' OR type LIKE '%Depression%' OR type LIKE '%Mental%'
               OR type LIKE '%Wellbeing%' OR type LIKE '%Emotion%'
            GROUP BY type ORDER BY n DESC
        """).fetchall()
        # También buscar por value_str que contenga mood/emotion keywords
        sample = conn.execute("""
            SELECT DISTINCT type, value_str FROM records
            WHERE value_str LIKE '%Happy%' OR value_str LIKE '%Sad%' 
               OR value_str LIKE '%Anxious%' OR value_str LIKE '%Calm%'
               OR value_str LIKE '%Depressed%'
            LIMIT 10
        """).fetchall()
    return jsonify({
        'types': [dict(r) for r in rows],
        'mood_samples': [dict(r) for r in sample]
    })


@main_bp.route('/api/debug/noise-check')
@login_required
def debug_noise_check():
    """Diagnóstico del ruido ambiental."""
    from services.db import get_conn, DB_FILE
    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})
    with get_conn() as conn:
        # Días con datos
        days = conn.execute(
            "SELECT date_day, COUNT(*) as n, AVG(value) as avg_db "
            "FROM records WHERE type='HKQuantityTypeIdentifierEnvironmentalAudioExposure' "
            "AND value IS NOT NULL GROUP BY date_day ORDER BY date_day DESC LIMIT 5"
        ).fetchall()
        # Muestra de registros raw
        sample = conn.execute(
            "SELECT date_day, substr(start_date,1,19) as t, value "
            "FROM records WHERE type='HKQuantityTypeIdentifierEnvironmentalAudioExposure' "
            "AND value IS NOT NULL ORDER BY start_date DESC LIMIT 5"
        ).fetchall()
        # Test de la query de serie horaria para el día más reciente
        last_day = days[0]['date_day'] if days else None
        series = []
        if last_day:
            series = conn.execute(
                "SELECT substr(start_date,11,6) as t, AVG(value) as v "
                "FROM records WHERE type='HKQuantityTypeIdentifierEnvironmentalAudioExposure' "
                "AND date_day=? AND value IS NOT NULL "
                "GROUP BY substr(start_date,1,13) ORDER BY start_date",
                (last_day,)
            ).fetchall()
    return jsonify({
        'recent_days': [dict(r) for r in days],
        'sample_raw':  [dict(r) for r in sample],
        'series_test': {'date': last_day, 'points': len(series), 'sample': [dict(r) for r in series[:3]]}
    })
