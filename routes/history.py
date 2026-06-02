from flask import Blueprint, render_template, jsonify, request
from services.db import get_history, get_history_compare
from datetime import datetime

# Caché: invalida solo cuando hay nueva importación
_HIST_CACHE = {}   # { (metric, period): (timestamp, data) }
_HIST_TTL   = 3600 * 24  # 24 horas — los datos solo cambian al importar

def _hist_cache_get(key):
    if key in _HIST_CACHE:
        ts, data = _HIST_CACHE[key]
        if (datetime.now() - ts).total_seconds() < _HIST_TTL:
            return data
    return None

def _hist_cache_set(key, data):
    _HIST_CACHE[key] = (datetime.now(), data)

def invalidate_hist_cache():
    _HIST_CACHE.clear()

history_bp = Blueprint('hist', __name__)

@history_bp.route('/historico')
def history_page():
    return render_template('history.html')

@history_bp.route('/api/history')
def api_history():
    metric = request.args.get('metric', 'pasos')
    period = request.args.get('period', 'month')
    key    = (metric, period)
    cached = _hist_cache_get(key)
    if cached:
        return jsonify(cached)
    data = get_history_compare(metric, period)
    _hist_cache_set(key, data)
    return jsonify(data)
