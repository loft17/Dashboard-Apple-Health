"""routes/ecg.py"""

from flask import Blueprint, jsonify, render_template, request
from services.ecg import list_ecg_files, get_ecg_for_date, get_ecg_by_filename

ecg_bp = Blueprint('ecg', __name__)


@ecg_bp.route('/ecg')
def ecg_list():
    """Página con listado de todos los ECGs disponibles."""
    ecgs = list_ecg_files()
    return render_template('ecg.html', ecgs=ecgs)


@ecg_bp.route('/api/ecg/list')
def api_ecg_list():
    return jsonify(list_ecg_files())


@ecg_bp.route('/api/ecg/date/<date_str>')
def api_ecg_date(date_str):
    """ECGs de una fecha concreta con muestras completas."""
    ecgs = get_ecg_for_date(date_str)
    if not ecgs:
        return jsonify([])
    # Downsample para la API: enviar 1 de cada 2 muestras (256 Hz) para reducir payload
    for ecg in ecgs:
        ecg['samples'] = ecg['samples'][::2]
        ecg['meta']['sample_rate'] = ecg['meta']['sample_rate'] // 2
    return jsonify(ecgs)


@ecg_bp.route('/api/ecg/file/<filename>')
def api_ecg_file(filename):
    """ECG completo por nombre de fichero (resolución completa 512 Hz)."""
    ecg = get_ecg_by_filename(filename)
    if not ecg:
        return jsonify({'error': 'No encontrado'}), 404
    return jsonify(ecg)
