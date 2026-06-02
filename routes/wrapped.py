"""routes/wrapped.py — Resumen anual estilo Wrapped."""
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from datetime import datetime

wrapped_bp = Blueprint('wrapped', __name__)

@wrapped_bp.route('/año')
@login_required
def wrapped_page():
    year = int(request.args.get('year', datetime.now().year))
    return render_template('wrapped.html', year=year,
                           current_year=datetime.now().year)

@wrapped_bp.route('/api/wrapped/<int:year>')
@login_required
def api_wrapped(year):
    from services.db import get_conn, DB_FILE, get_history
    from services.workout import list_workouts
    from datetime import datetime as dt, timedelta
    from collections import defaultdict

    if not DB_FILE.exists():
        return jsonify({'error': 'No DB'})

    date_from = f'{year}-01-01'
    date_to   = f'{year}-12-31'

    with get_conn() as conn:
        # Pasos totales y por día
        steps_rows = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierStepCount' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL "
            "GROUP BY date_day ORDER BY date_day",
            (date_from, date_to)
        ).fetchall()

        # Distancia total — respetar unidad (algunos dispositivos guardan km, otros m)
        dist_rows = conn.execute(
            "SELECT value, unit FROM records "
            "WHERE type='HKQuantityTypeIdentifierDistanceWalkingRunning' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL",
            (date_from, date_to)
        ).fetchall()

        # Calorías activas totales
        cal_row = conn.execute(
            "SELECT SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierActiveEnergyBurned' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL",
            (date_from, date_to)
        ).fetchone()

        # Pisos subidos
        pisos_row = conn.execute(
            "SELECT SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierFlightsClimbed' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL",
            (date_from, date_to)
        ).fetchone()

        # FC en reposo media
        fc_row = conn.execute(
            "SELECT AVG(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierRestingHeartRate' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL",
            (date_from, date_to)
        ).fetchone()

        # HRV medio
        hrv_row = conn.execute(
            "SELECT AVG(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierHeartRateVariabilitySDNN' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL",
            (date_from, date_to)
        ).fetchone()

        # Días con datos
        days_row = conn.execute(
            "SELECT COUNT(DISTINCT date_day) as v FROM records "
            "WHERE date_day>=? AND date_day<=?",
            (date_from, date_to)
        ).fetchone()

        # Mejor día de pasos
        best_steps = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierStepCount' "
            "AND date_day>=? AND date_day<=? AND value IS NOT NULL "
            "GROUP BY date_day ORDER BY v DESC LIMIT 1",
            (date_from, date_to)
        ).fetchone()

        # Sueño
        sleep_rows = conn.execute(
            "SELECT substr(end_date,1,10) as g, "
            "SUM(CAST((julianday(substr(end_date,1,19))-julianday(substr(start_date,1,19)))*1440 AS INTEGER)) as v "
            "FROM records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' "
            "AND date_day>=? AND date_day<=? "
            "AND value_str NOT LIKE '%InBed%' AND value_str NOT LIKE '%Awake%' "
            "GROUP BY g ORDER BY g",
            (date_from, date_to)
        ).fetchall()

    # Procesar sueño
    sleep_days = [(r['g'], r['v']/60) for r in sleep_rows if r['v'] and r['v'] > 180]
    total_sleep_h  = sum(h for _,h in sleep_days)
    avg_sleep_h    = total_sleep_h / len(sleep_days) if sleep_days else 0
    best_sleep     = max(sleep_days, key=lambda x:x[1], default=(None,0))
    worst_sleep    = min(sleep_days, key=lambda x:x[1], default=(None,0))

    # Pasos por mes para gráfica
    steps_by_month = defaultdict(float)
    steps_vals = []
    for r in steps_rows:
        m = int(r['date_day'][5:7])
        steps_by_month[m] += r['v']
        steps_vals.append(r['v'])

    # Mejor y peor semana (por pasos)
    steps_by_week = defaultdict(float)
    for r in steps_rows:
        d = dt.strptime(r['date_day'], '%Y-%m-%d')
        wk = d.strftime('%Y-%W')
        steps_by_week[wk] += r['v']
    best_week  = max(steps_by_week.items(), key=lambda x:x[1], default=(None,0))
    worst_week = min(steps_by_week.items(), key=lambda x:x[1], default=(None,0))

    # Entrenamientos del año
    all_wk = list_workouts()
    year_wk = [w for w in all_wk if w.get('date','').startswith(str(year))]
    total_wk_km   = sum(float(w.get('distance_km') or 0) for w in year_wk)
    total_wk_min  = sum(float(w.get('duration_min') or 0) for w in year_wk)
    from services.workout import WORKOUT_NAMES
    wk_by_type = defaultdict(int)
    for w in year_wk:
        raw_type = w.get('type', 'Otro') or 'Otro'
        label = WORKOUT_NAMES.get(raw_type, (raw_type, '🏅'))[0]
        wk_by_type[label] += 1
    # Mejor entrenamiento: primero por distancia, luego por duración, luego por calorías
    def _wk_score(w):
        km  = float(w.get('distance_km') or 0)
        min_ = float(w.get('duration_min') or 0)
        kcal = float(w.get('kcal') or 0)
        return (km, min_/60, kcal/1000)

    best_wk = max(year_wk, key=_wk_score, default=None)

    # Días sin datos
    all_days = set()
    d = dt.strptime(date_from, '%Y-%m-%d')
    end = dt.strptime(min(date_to, datetime.now().strftime('%Y-%m-%d')), '%Y-%m-%d')
    while d <= end:
        all_days.add(d.strftime('%Y-%m-%d'))
        d += timedelta(days=1)
    days_with_steps = {r['date_day'] for r in steps_rows if r['v'] > 500}
    active_streak = 0
    for day in sorted(days_with_steps, reverse=True):
        active_streak += 1
        break  # simplificado — solo contar racha actual

    return jsonify({
        'year':          year,
        'total_steps':   round(sum(r['v'] for r in steps_rows)),
        'total_km':      round(sum(
                float(r['value'] or 0) if (r['unit'] or '').lower() in ('km','kilometer','kilometers')
                else float(r['value'] or 0)/1000
                for r in dist_rows
            ), 1),
        'total_cal':     round(float(cal_row['v'] or 0)),
        'total_pisos':   round(float(pisos_row['v'] or 0)),
        'avg_fc_reposo': round(float(fc_row['v'] or 0), 1),
        'avg_hrv':       round(float(hrv_row['v'] or 0), 1),
        'days_with_data': days_row['v'] or 0,
        'best_day_steps': {'date': best_steps['date_day'] if best_steps else None, 'steps': round(best_steps['v']) if best_steps else 0},
        'avg_sleep_h':   round(avg_sleep_h, 1),
        'total_sleep_h': round(total_sleep_h, 1),
        'best_sleep':    {'date': best_sleep[0], 'h': round(best_sleep[1], 1)},
        'worst_sleep':   {'date': worst_sleep[0], 'h': round(worst_sleep[1], 1)},
        'steps_by_month': [round(steps_by_month.get(m, 0)) for m in range(1, 13)],
        'best_week':     {'week': best_week[0], 'steps': round(best_week[1])},
        'worst_week':    {'week': worst_week[0], 'steps': round(worst_week[1])},
        'workouts':      {'count': len(year_wk), 'km': round(total_wk_km, 1), 'hours': round(total_wk_min/60, 1), 'by_type': dict(wk_by_type)},
        'best_workout': {
            'date': best_wk.get('date'),
            'type': WORKOUT_NAMES.get(best_wk.get('type',''), (best_wk.get('type','Entrenamiento'),'🏅'))[0],
            'km':   round(float(best_wk.get('distance_km') or 0), 2),
            'dur':  round(float(best_wk.get('duration_min') or 0)),
            'kcal': round(float(best_wk.get('kcal') or 0)),
        } if best_wk else None,
    })
