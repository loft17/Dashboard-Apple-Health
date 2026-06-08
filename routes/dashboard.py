"""routes/dashboard.py"""

from flask import Blueprint, jsonify, render_template, request
from datetime import datetime

# ── Caché persistente en disco ──────────────────────────────────────────────────
from services.cache import (get_cached_day, set_cached_day,
                             invalidate_all, invalidate_from,
                             is_today, get_last_import_date)
import threading
_MEM_CACHE = {}
_MEM_LOCK  = threading.Lock()

def _cache_get(date_str):
    if is_today(date_str):
        with _MEM_LOCK:
            if date_str in _MEM_CACHE:
                ts, data = _MEM_CACHE[date_str]
                if (datetime.now() - ts).total_seconds() < 300:
                    return data
        return None
    return get_cached_day(date_str)

def _cache_set(date_str, data):
    if is_today(date_str):
        with _MEM_LOCK:
            _MEM_CACHE[date_str] = (datetime.now(), data)
    else:
        set_cached_day(date_str, data)

def invalidate_cache():
    """Al importar: solo invalida desde el último día importado, no todo."""
    with _MEM_LOCK:
        _MEM_CACHE.clear()
    last = get_last_import_date()
    if last:
        invalidate_from(last)  # solo el día del import y posteriores
    else:
        invalidate_all()

from services.workout import list_workouts as _list_workouts, _WORKOUT_CACHE
from services.db import (
    get_recovery_score, get_vo2_trend,
    load_stats, get_today_summary, get_available_dates,
    debug_type_sample, get_heart_rate_day, get_hrv_day,
    get_sleep_day, get_active_energy_series,
    get_exercise_minutes, get_stand_hours, get_steps_for_day,
    get_distance_km, get_calories, get_extra_metrics, get_all_metrics
)

dashboard_bp = Blueprint('dashboard', __name__)


def _validate_date(date_str):
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return date_str
    except ValueError:
        return datetime.now().strftime('%Y-%m-%d')


@dashboard_bp.route('/dashboard')
def dashboard():
    stats     = load_stats()
    daterange = get_available_dates()

    # Si no se pide fecha concreta, cargar el último día con datos de pasos
    requested = request.args.get('date')
    if requested:
        date_str = _validate_date(requested)
    else:
        # Buscar último día con datos reales
        last_with_data = daterange.get('last_with_steps') or daterange.get('date_max') or datetime.now().strftime('%Y-%m-%d')
        date_str = _validate_date(last_with_data)

    return render_template('dashboard.html', stats=stats, date=date_str, daterange=daterange)


@dashboard_bp.route('/api/day')
def api_day():
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Formato inválido'}), 400

    # Caché
    cached = _cache_get(date_str)
    if cached:
        return jsonify(cached)

    result = _build_day_data(date_str)
    _cache_set(date_str, result)
    return jsonify(result)


def _build_day_data(date_str: str) -> dict:
    """Construye los datos del día. Usado por api_day y el warm-up del caché."""
    from services.db import get_day_data_batch, get_sleep_score
    batch          = get_day_data_batch(date_str)
    sleep          = get_sleep_day(date_str)
    recovery_score = get_recovery_score(date_str)
    sleep_score_d  = get_sleep_score(date_str)
    try:
        all_wk   = _list_workouts()
        workouts = [{**w, '_idx': i} for i, w in enumerate(all_wk) if w['date'] == date_str]
    except Exception:
        workouts = []
    from services.db import get_day_compare
    compare = get_day_compare(date_str)

    return {
        'date':           date_str,
        'sleep_score':    sleep_score_d,
        'compare':        compare,
        'steps':          batch.get('steps', 0),
        'steps_series':   batch.get('steps_series', []),
        'distance_km':    batch.get('distance_km', 0),
        'calories':       batch.get('calories', 0),
        'ex_min':         batch.get('ex_min', 0),
        'stand_h':        batch.get('stand_h', 0),
        'hr':             batch.get('hr', {}),
        'hrv':            batch.get('hrv', {}),
        'sleep':          sleep,
        'workouts':       workouts,
        'cal_series':     batch.get('cal_series', []),
        'extra':          {},
        'all_metrics':    {},
        'recovery_score': recovery_score,
        'vo2_trend':      None,
    }


@dashboard_bp.route('/api/day/detail')
def api_day_detail():
    """Métricas detalladas — cargadas lazy cuando el usuario expande el panel."""
    date_str = request.args.get('date') or datetime.now().strftime('%Y-%m-%d')
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        date_str = datetime.now().strftime('%Y-%m-%d')

    all_metrics = get_all_metrics(date_str)
    vo2_trend   = get_vo2_trend(date_str)
    extra       = get_extra_metrics(date_str)
    # Incluir sleep con segments para la gráfica de /salud/
    sleep = get_sleep_day(date_str)

    return jsonify({
        'date':        date_str,
        'all_metrics': all_metrics,
        'vo2_trend':   vo2_trend,
        'extra':       extra,
        'sleep':       sleep,
    })


@dashboard_bp.route('/api/day/compare')
def api_day_compare():
    from datetime import timedelta
    from services.db import get_steps_for_day, get_calories, get_heart_rate_day
    today = datetime.now()
    days  = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(7,14)]
    steps = [get_steps_for_day(d) for d in days]
    cals  = [get_calories(d) for d in days]
    hrs   = [get_heart_rate_day(d) for d in days]
    steps_avg = sum(steps)/7
    cals_avg  = sum(cals)/7
    hr_vals   = [h['avg'] for h in hrs if h and h.get('avg')]
    hr_avg    = sum(hr_vals)/len(hr_vals) if hr_vals else 0
    return jsonify({'steps':round(steps_avg),'calories':round(cals_avg),'hr':round(hr_avg,1)})

@dashboard_bp.route('/api/calendar')
def api_calendar():
    """Datos de actividad para el calendario mensual."""
    from services.db import get_conn, DB_FILE
    from datetime import datetime
    year  = int(request.args.get('year',  datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    if not DB_FILE.exists():
        return jsonify([])
    # Rango del mes
    import calendar
    _, days_in_month = calendar.monthrange(year, month)
    date_from = f'{year}-{month:02d}-01'
    date_to   = f'{year}-{month:02d}-{days_in_month:02d}'
    with get_conn() as conn:
        # Pasos por día
        steps = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierStepCount' "
            "AND date_day>=? AND date_day<=? GROUP BY date_day",
            (date_from, date_to)
        ).fetchall()
        # Calorías activas por día
        cals = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierActiveEnergyBurned' "
            "AND date_day>=? AND date_day<=? GROUP BY date_day",
            (date_from, date_to)
        ).fetchall()
        # Sueño (horas) por día usando Python para evitar julianday con TZ
        sleep_rows = conn.execute(
            "SELECT substr(end_date,1,10) as g, "
            "substr(start_date,1,19) as s, substr(end_date,1,19) as e "
            "FROM records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' "
            "AND date_day>=? AND date_day<=? "
            "AND value_str NOT LIKE '%InBed%' AND value_str NOT LIKE '%Awake%'",
            (date_from, date_to)
        ).fetchall()

    from datetime import datetime as _dt
    sleep_map = {}
    for r in sleep_rows:
        try:
            s = _dt.strptime(r['s'], '%Y-%m-%d %H:%M:%S')
            e = _dt.strptime(r['e'], '%Y-%m-%d %H:%M:%S')
            mins = (e-s).total_seconds()/60
            if mins > 0:
                sleep_map[r['g']] = sleep_map.get(r['g'], 0) + mins
        except Exception:
            pass

    steps_map = {r['date_day']: r['v'] for r in steps}
    cals_map  = {r['date_day']: r['v'] for r in cals}

    result = []
    for day in range(1, days_in_month+1):
        d = f'{year}-{month:02d}-{day:02d}'
        s = steps_map.get(d, 0)
        result.append({
            'date':    d,
            'steps':   round(s or 0),
            'cal':     round(cals_map.get(d, 0) or 0),
            'sleep_h': round((sleep_map.get(d, 0) or 0) / 60, 1),
        })
    return jsonify(result)


@dashboard_bp.route('/api/date-range')
def date_range():
    return jsonify(get_available_dates())


@dashboard_bp.route('/api/debug/distance')
def debug_distance():
    return jsonify({
        'walking': debug_type_sample('HKQuantityTypeIdentifierDistanceWalkingRunning'),
        'cycling': debug_type_sample('HKQuantityTypeIdentifierDistanceCycling'),
    })
