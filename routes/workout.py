"""routes/workout.py"""
from flask import Blueprint, jsonify, render_template, request
from services.workout import list_workouts, get_workout_route
from services.db import get_conn, DB_FILE

workout_bp = Blueprint('workout', __name__)


@workout_bp.route('/workouts')
def workouts_page():
    # Solo metadatos para el template — sin muestras GPS
    # La primera carga muestra el último mes por defecto
    workouts = list_workouts()
    return render_template('workouts.html', workouts=workouts)


@workout_bp.route('/api/workouts/list')
def api_workout_list():
    from flask import request as req
    ws = list_workouts()
    period = req.args.get('period', 'all')
    if period == 'week':
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
        ws = [w for w in ws if w['date'] >= cutoff]
    elif period == 'month':
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        ws = [w for w in ws if w['date'] >= cutoff]
    elif period == 'year':
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        ws = [w for w in ws if w['date'] >= cutoff]
    return jsonify(ws)


@workout_bp.route('/api/workouts/route')
def api_workout_route():
    gpx = request.args.get('gpx', '')
    if not gpx:
        return jsonify({'error': 'gpx param required'}), 400
    data = get_workout_route(gpx)
    if not data:
        return jsonify({'error': 'Ruta no encontrada'}), 404

    # Reducir puntos para no saturar el navegador (máx 2000 puntos)
    pts = data['points']
    if len(pts) > 2000:
        step = len(pts) // 2000
        pts  = pts[::step]
    data['points'] = pts
    return jsonify(data)



@workout_bp.route('/api/workouts/stats-extra')
def api_workout_stats_extra():
    """Pasos, calorías basales y clima para el rango del entreno."""
    start      = request.args.get('start', '')
    end        = request.args.get('end', '')
    lat        = request.args.get('lat', '')
    lon        = request.args.get('lon', '')
    dur_min    = float(request.args.get('dur_min', 0))
    kcal_active = float(request.args.get('kcal', 0))

    result = {}

    if DB_FILE.exists() and start and end:
        with get_conn() as conn:
            # Pasos en el rango → cadencia
            steps_row = conn.execute(
                'SELECT COALESCE(SUM(value),0) FROM records '
                'WHERE type=? AND start_date>=? AND start_date<=? AND value IS NOT NULL',
                ('HKQuantityTypeIdentifierStepCount', start, end)
            ).fetchone()
            steps = int(steps_row[0]) if steps_row else 0
            result['steps']    = steps
            result['cadence']  = round(steps / dur_min) if dur_min > 0 and steps > 0 else None

            # Calorías basales en el rango
            basal_row = conn.execute(
                'SELECT COALESCE(SUM(value),0) FROM records '
                'WHERE type=? AND start_date>=? AND start_date<=? AND value IS NOT NULL',
                ('HKQuantityTypeIdentifierBasalEnergyBurned', start, end)
            ).fetchone()
            kcal_basal = round(float(basal_row[0])) if basal_row else 0
            kcal_total = round(kcal_active + kcal_basal)
            result['kcal_basal']    = kcal_basal
            result['kcal_total']    = kcal_total
            result['kcal_active']   = round(kcal_active)
            result['pct_active']    = round(kcal_active / kcal_total * 100) if kcal_total > 0 else None
            result['pct_basal']     = round(kcal_basal  / kcal_total * 100) if kcal_total > 0 else None

    # Clima via Open-Meteo (gratuito, sin API key)
    if lat and lon and start:
        try:
            import urllib.request, json as _json
            date_only = start[:10]
            url = (f'https://archive-api.open-meteo.com/v1/archive?'
                   f'latitude={lat}&longitude={lon}&start_date={date_only}&end_date={date_only}'
                   f'&hourly=temperature_2m,weathercode,windspeed_10m,precipitation'
                   f'&timezone=Europe%2FMadrid')
            with urllib.request.urlopen(url, timeout=5) as resp:
                wdata = _json.loads(resp.read())
            # Coger la hora del inicio del entreno
            hour = int(start[11:13])
            h = wdata['hourly']
            result['weather'] = {
                'temp_c':    h['temperature_2m'][hour],
                'windspeed': h['windspeed_10m'][hour],
                'precip':    h['precipitation'][hour],
                'code':      h['weathercode'][hour],
            }
        except Exception as e:
            result['weather'] = None

    return jsonify(result)


@workout_bp.route('/api/workouts/heartrate')
def api_workout_heartrate():
    """FC con timestamps para un rango de tiempo del entreno."""
    start = request.args.get('start', '')
    end   = request.args.get('end', '')
    if not start or not end:
        return jsonify([])
    if not DB_FILE.exists():
        return jsonify([])
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND start_date>=? AND start_date<=? '
            'AND value IS NOT NULL ORDER BY start_date',
            ('HKQuantityTypeIdentifierHeartRate', start, end)
        ).fetchall()
    return jsonify([{'bpm': int(r['value']), 'time': r['start_date']} for r in rows])


@workout_bp.route('/workouts/<int:idx>')
def workout_detail(idx):
    """Página individual de un entrenamiento."""
    workouts = list_workouts()
    if idx < 0 or idx >= len(workouts):
        return 'Entrenamiento no encontrado', 404
    w = workouts[idx]
    return render_template('workout_detail.html', workout=w, idx=idx)
