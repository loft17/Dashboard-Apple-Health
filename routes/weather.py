"""routes/weather.py — Endpoints meteorológicos."""
from flask import Blueprint, jsonify, request
from flask_login import login_required

weather_bp = Blueprint('weather', __name__)


@weather_bp.route('/api/weather/day')
@login_required
def api_weather_day():
    from services.weather import get_weather_for_day, fetch_weather_range
    from datetime import datetime, timedelta
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    w = get_weather_for_day(date_str)
    if not w:
        # Intentar descargar
        try:
            week_ago = (datetime.strptime(date_str,'%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
            fetch_weather_range(week_ago, date_str)
            w = get_weather_for_day(date_str)
        except Exception as e:
            return jsonify({'error': str(e)})
    return jsonify(w or {})


@weather_bp.route('/api/weather/history')
@login_required
def api_weather_history():
    from services.weather import get_weather_history
    date_from = request.args.get('from', '2024-01-01')
    date_to   = request.args.get('to',   '2026-12-31')
    return jsonify(get_weather_history(date_from, date_to))


@weather_bp.route('/api/weather/sync', methods=['POST'])
@login_required
def api_weather_sync():
    """Sincroniza todos los días con datos de salud sin datos meteorológicos."""
    from services.weather import sync_missing_weather
    try:
        n = sync_missing_weather()
        return jsonify({'ok': True, 'synced': n})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})


@weather_bp.route('/api/weather/geocode')
@login_required
def api_geocode():
    from services.weather import geocode_city
    name = request.args.get('q', '')
    if not name:
        return jsonify([])
    return jsonify(geocode_city(name))


@weather_bp.route('/api/settings/city', methods=['POST'])
@login_required
def api_save_city():
    from services.db import set_config
    d = request.get_json() or {}
    name = d.get('name', '').strip()
    lat  = d.get('lat')
    lon  = d.get('lon')
    if not name or lat is None or lon is None:
        return jsonify({'ok': False, 'error': 'Faltan datos'})
    set_config('city_name', name)
    set_config('city_lat',  str(lat))
    set_config('city_lon',  str(lon))
    return jsonify({'ok': True})
