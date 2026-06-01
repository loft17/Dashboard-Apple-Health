"""
routes/main.py
Blueprint para la página de inicio y la subida del ZIP.
"""

import threading
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request, Response, stream_with_context
import json, queue, time

from services.db       import load_stats
from services.importer import import_state, process_zip, progress_queue

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
def index():
    stats = load_stats()
    return render_template('index.html', stats=stats)


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
