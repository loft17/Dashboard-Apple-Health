"""services/gamification.py — Rachas, logros y retos."""
from datetime import datetime, timedelta
from collections import defaultdict
from services.db import get_conn, DB_FILE, get_user_goals

# ── Definición de logros ──────────────────────────────────────────────────────
# Cada logro puede tener:
#   count_mode: True  → se consigue múltiples veces, muestra contador
#   threshold:        → valor necesario para conseguirlo
#   type:             → qué métrica evalúa

ACHIEVEMENTS_DEF = [

    # ── Objetivo de movimiento (pasos alcanzados) ─────────────────────────────
    {'key': 'move_goal_500', 'label': '500 objetivos de movimiento', 'emoji': '🎯',
     'desc': '500 veces alcanzar el objetivo diario de pasos',
     'type': 'move_goal', 'threshold': 500, 'count_mode': False},

    # ── Moverse X% del objetivo ───────────────────────────────────────────────
    {'key': 'move_200pct', 'label': 'Moverse al 200%', 'emoji': '💪',
     'desc': 'Andar el doble de tu objetivo de pasos en un día',
     'type': 'move_pct', 'threshold': 2.0, 'count_mode': True},
    {'key': 'move_300pct', 'label': 'Moverse al 300%', 'emoji': '🚀',
     'desc': 'Andar el triple de tu objetivo de pasos en un día',
     'type': 'move_pct', 'threshold': 3.0, 'count_mode': True},
    {'key': 'move_400pct', 'label': 'Moverse al 400%', 'emoji': '⚡',
     'desc': 'Andar 4 veces tu objetivo de pasos en un día',
     'type': 'move_pct', 'threshold': 4.0, 'count_mode': True},

    # ── Calorías ─────────────────────────────────────────────────────────────
    {'key': 'kcal_500',    'label': 'Gastar 500 kcal',            'emoji': '🔥',
     'desc': 'Quemar 500 kcal activas en un día',
     'type': 'calories_day', 'threshold': 500, 'count_mode': True},

    # ── Distancia en una semana ──────────────────────────────────────────────
    {'key': 'week_5k',      'label': '5 km en una semana',        'emoji': '🚶',
     'desc': 'Caminar/correr 5 km en 7 días consecutivos',
     'type': 'dist_week', 'threshold': 5,    'count_mode': True},
    {'key': 'week_marathon', 'label': 'Maratón en una semana',    'emoji': '🏃',
     'desc': '42 km acumulados en una semana',
     'type': 'dist_week', 'threshold': 42.2, 'count_mode': True},
    {'key': 'week_100k',    'label': '100 km en una semana',      'emoji': '💪',
     'desc': '100 km en 7 días consecutivos',
     'type': 'dist_week', 'threshold': 100,  'count_mode': True},

    # ── Distancia en un mes ───────────────────────────────────────────────────
    {'key': 'month_50k',    'label': '50 km en un mes',           'emoji': '📅',
     'desc': '50 km acumulados en un mes natural',
     'type': 'dist_month', 'threshold': 50,  'count_mode': True},
    {'key': 'month_marathon','label': 'Maratón en un mes',        'emoji': '🗓️',
     'desc': '42 km acumulados en un mes',
     'type': 'dist_month', 'threshold': 42.2,'count_mode': True},
    {'key': 'month_100k',   'label': '100 km en un mes',          'emoji': '🌍',
     'desc': '100 km en un mes natural',
     'type': 'dist_month', 'threshold': 100, 'count_mode': True},
    {'key': 'month_200k',   'label': '200 km en un mes',          'emoji': '🚀',
     'desc': '200 km en un mes natural',
     'type': 'dist_month', 'threshold': 200, 'count_mode': True},

    # ── Distancia en un año ───────────────────────────────────────────────────
    {'key': 'year_500k',    'label': '500 km en un año',          'emoji': '🏅',
     'desc': '500 km acumulados en un año natural',
     'type': 'dist_year', 'threshold': 500,  'count_mode': True},
    {'key': 'year_1000k',   'label': '1.000 km en un año',        'emoji': '🥈',
     'desc': '1.000 km en un año natural',
     'type': 'dist_year', 'threshold': 1000, 'count_mode': True},
    {'key': 'year_camino',  'label': 'El Camino de Santiago',     'emoji': '🛤️',
     'desc': '800 km en un año (la distancia del Camino Francés)',
     'type': 'dist_year', 'threshold': 800,  'count_mode': True},
    {'key': 'year_2000k',   'label': '2.000 km en un año',        'emoji': '🥇',
     'desc': '2.000 km en un año natural',
     'type': 'dist_year', 'threshold': 2000, 'count_mode': True},

    # ── Logros especiales (distancia acumulada total) ─────────────────────────
    {'key': 'special_moon',    'label': 'Hasta la Luna',          'emoji': '🌙',
     'desc': 'Acumular 384.400 km andados (distancia Tierra-Luna)',
     'type': 'dist_total', 'threshold': 384400, 'count_mode': False},
    {'key': 'special_world',   'label': 'Vuelta al Mundo',        'emoji': '🌍',
     'desc': 'Acumular 40.075 km andados (circunferencia de la Tierra)',
     'type': 'dist_total', 'threshold': 40075,  'count_mode': False},
    {'key': 'special_equator', 'label': 'Al Ecuador',             'emoji': '🌐',
     'desc': 'Acumular 10.000 km andados',
     'type': 'dist_total', 'threshold': 10000,  'count_mode': False},
    {'key': 'special_spain',   'label': 'España de punta a punta','emoji': '🇪🇸',
     'desc': 'Acumular 1.200 km (de Tarifa a los Pirineos)',
     'type': 'dist_total', 'threshold': 1200,   'count_mode': False},
    {'key': 'special_santiago', 'label': 'El Camino de Santiago', 'emoji': '⛪', 'desc': 'Acumular 800 km andados en total',
     'type': 'dist_total', 'threshold': 800,    'count_mode': False},

    # ── Semanas/mes/año perfecto ──────────────────────────────────────────────
    {'key': 'week_steps',  'label': 'Semana perfecta andando',    'emoji': '📅',
     'desc': '7 días seguidos alcanzando el objetivo de pasos',
     'type': 'streak_steps_week', 'threshold': 7,  'count_mode': True},
    {'key': 'week_stand',  'label': 'Semana perfecta de pie',     'emoji': '🧍',
     'desc': '7 días seguidos alcanzando el objetivo de horas de pie',
     'type': 'streak_stand_week', 'threshold': 7,  'count_mode': True},
    {'key': 'month_steps', 'label': 'Mes perfecto andando',       'emoji': '🗓️',
     'desc': 'Un mes entero alcanzando el objetivo de pasos cada día',
     'type': 'streak_steps_week', 'threshold': 28, 'count_mode': True},
    {'key': 'year_steps',  'label': 'Año perfecto andando',       'emoji': '🏆',
     'desc': '365 días seguidos alcanzando el objetivo de pasos',
     'type': 'streak_steps_week', 'threshold': 365,'count_mode': True},

    # ── Pasos en un día ───────────────────────────────────────────────────────
    {'key': 'day_10k',     'label': '10.000 pasos en un día',     'emoji': '👟',
     'desc': 'Superar 10.000 pasos en un solo día',
     'type': 'steps_day', 'threshold': 10_000,  'count_mode': True},
    {'key': 'day_20k',     'label': '20.000 pasos en un día',     'emoji': '🏃',
     'desc': 'Superar 20.000 pasos en un solo día',
     'type': 'steps_day', 'threshold': 20_000,  'count_mode': True},
    {'key': 'day_30k',     'label': '30.000 pasos en un día',     'emoji': '🌟',
     'desc': 'Superar 30.000 pasos en un solo día',
     'type': 'steps_day', 'threshold': 30_000,  'count_mode': True},
    {'key': 'day_40k',     'label': '40.000 pasos en un día',     'emoji': '🔥',
     'desc': 'Superar 40.000 pasos en un solo día',
     'type': 'steps_day', 'threshold': 40_000,  'count_mode': True},
    {'key': 'day_50k',     'label': '50.000 pasos en un día',     'emoji': '👑',
     'desc': 'Superar 50.000 pasos en un solo día',
     'type': 'steps_day', 'threshold': 50_000,  'count_mode': True},

    # ── Entrenamientos ────────────────────────────────────────────────────────
    {'key': 'workout_10',  'label': '10 entrenamientos',          'emoji': '🥉',
     'desc': 'Completar 10 entrenamientos registrados',
     'type': 'workouts_total', 'threshold': 10,  'count_mode': False},
    {'key': 'workout_50',  'label': '50 entrenamientos',          'emoji': '🥈',
     'desc': 'Completar 50 entrenamientos registrados',
     'type': 'workouts_total', 'threshold': 50,  'count_mode': False},
    {'key': 'workout_100', 'label': '100 entrenamientos',         'emoji': '🥇',
     'desc': 'Completar 100 entrenamientos registrados',
     'type': 'workouts_total', 'threshold': 100, 'count_mode': False},
    {'key': 'workout_500', 'label': '500 entrenamientos',         'emoji': '💎',
     'desc': 'Completar 500 entrenamientos registrados',
     'type': 'workouts_total', 'threshold': 500, 'count_mode': False},

    # ── Pasos acumulados totales ──────────────────────────────────────────────
    {'key': 'km_1000',     'label': '1.000 km andados',           'emoji': '🗺️',
     'desc': 'Acumular 1.000 km caminando y corriendo en total',
     'type': 'dist_total', 'threshold': 1000, 'count_mode': False},

    {'key': 'total_1k',    'label': '1.000 pasos',                'emoji': '👣',
     'desc': 'Acumular 1.000 pasos en total',
     'type': 'steps_total', 'threshold': 1_000,       'count_mode': False},
    {'key': 'total_100k',  'label': '100.000 pasos',              'emoji': '🚶',
     'desc': 'Acumular 100.000 pasos en total',
     'type': 'steps_total', 'threshold': 100_000,     'count_mode': False},
    {'key': 'total_1M',    'label': '1.000.000 de pasos',         'emoji': '🌍',
     'desc': 'Acumular un millón de pasos',
     'type': 'steps_total', 'threshold': 1_000_000,   'count_mode': False},
    {'key': 'total_5M',    'label': '5.000.000 de pasos',         'emoji': '🌎',
     'desc': 'Acumular 5 millones de pasos',
     'type': 'steps_total', 'threshold': 5_000_000,   'count_mode': False},
    {'key': 'total_10M',   'label': '10.000.000 de pasos',        'emoji': '🌏',
     'desc': 'Acumular 10 millones de pasos',
     'type': 'steps_total', 'threshold': 10_000_000,  'count_mode': False},
    {'key': 'total_50M',   'label': '50.000.000 de pasos',        'emoji': '🚀',
     'desc': 'Acumular 50 millones de pasos',
     'type': 'steps_total', 'threshold': 50_000_000,  'count_mode': False},
]

# ── Definición de rachas ──────────────────────────────────────────────────────
STREAKS_DEF = {
    'steps_goal': {'label': 'Objetivo de pasos', 'emoji': '👟', 'unit': 'días'},
    'steps_10k':  {'label': 'Pasos > 10.000',   'emoji': '🔥', 'unit': 'días'},
    'sleep_7h':   {'label': 'Sueño > 7h',        'emoji': '🌙', 'unit': 'noches'},
    'rings':      {'label': 'Anillos completos',  'emoji': '⭕', 'unit': 'días'},
}


def _get_best_streak(key: str) -> int:
    try:
        with get_conn() as conn:
            r = conn.execute("SELECT best FROM streaks WHERE key=?", (key,)).fetchone()
            return int(r['best']) if r else 0
    except Exception:
        return 0


def _save_streak(key: str, current: int, best: int, last_date: str):
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO streaks (key,current,best,last_date) VALUES (?,?,?,?)",
                (key, current, max(best, _get_best_streak(key)), last_date)
            )
            conn.commit()
    except Exception:
        pass


def compute_streaks() -> dict:
    if not DB_FILE.exists():
        return {}
    goals = get_user_goals()
    steps_goal = int(goals.get('steps_daily', 10000))
    stand_goal = int(goals.get('stand_hours', 12))

    since = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')

    with get_conn() as conn:
        steps_rows = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierStepCount' "
            "AND date_day>=? GROUP BY date_day ORDER BY date_day DESC",
            (since,)
        ).fetchall()
        stand_rows = conn.execute(
            "SELECT date_day, COUNT(*) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierAppleStandHour' "
            "AND value_str LIKE '%Stood%' AND date_day>=? "
            "GROUP BY date_day ORDER BY date_day DESC",
            (since,)
        ).fetchall()
        sleep_rows = conn.execute(
            "SELECT substr(end_date,1,10) as g, "
            "SUM(CAST((julianday(substr(end_date,1,19))-julianday(substr(start_date,1,19)))*1440 AS INTEGER)) as v "
            "FROM records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' "
            "AND date_day>=? AND value_str NOT LIKE '%InBed%' AND value_str NOT LIKE '%Awake%' "
            "GROUP BY g ORDER BY g DESC",
            (since,)
        ).fetchall()

    steps_map = {r['date_day']: r['v'] for r in steps_rows}
    stand_map = {r['date_day']: r['v'] for r in stand_rows}
    sleep_map = {r['g']: r['v']/60 for r in sleep_rows if r['v'] and r['v'] > 180}

    def _streak(date_map, threshold, key, goal_label=''):
        current = 0; best = 0; last_ok = None
        for i in range(400):
            ds = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            if date_map.get(ds, 0) >= threshold:
                current += 1; best = max(best, current); last_ok = ds
            elif i > 0:
                break
        _save_streak(key, current, best, last_ok)
        return {'current': current, 'best': max(best, _get_best_streak(key)),
                'last': last_ok, 'goal': threshold}

    result = {
        'steps_goal': _streak(steps_map, steps_goal, 'steps_goal'),
        'steps_10k':  _streak(steps_map, 10000,      'steps_10k'),
        'sleep_7h':   _streak(sleep_map, 7.0,         'sleep_7h'),
        'rings':      _streak(
            {d: min(steps_map.get(d,0)/steps_goal,
                    stand_map.get(d,0)/stand_goal) for d in steps_map},
            1.0, 'rings'
        ),
    }
    return result


def compute_achievements() -> list:
    if not DB_FILE.exists():
        return []

    goals    = get_user_goals()
    steps_goal = int(goals.get('steps_daily', 10000))
    cal_goal   = int(goals.get('calories_daily', 500))
    stand_goal = int(goals.get('stand_hours', 12))
    ex_goal    = int(goals.get('exercise_min', 30))

    since_all = '2010-01-01'
    today     = datetime.now().strftime('%Y-%m-%d')

    with get_conn() as conn:
        # Pasos por día — todo el historial
        steps_rows = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierStepCount' "
            "GROUP BY date_day ORDER BY date_day",
        ).fetchall()

        # Calorías por día
        cal_rows = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierActiveEnergyBurned' "
            "GROUP BY date_day ORDER BY date_day"
        ).fetchall()

        # De pie por día
        stand_rows = conn.execute(
            "SELECT date_day, COUNT(*) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierAppleStandHour' "
            "AND value_str LIKE '%Stood%' GROUP BY date_day"
        ).fetchall()

        # Ejercicio por día
        ex_rows = conn.execute(
            "SELECT date_day, SUM(value) as v FROM records "
            "WHERE type='HKQuantityTypeIdentifierAppleExerciseTime' "
            "GROUP BY date_day"
        ).fetchall()

    steps_by_day  = {r['date_day']: r['v'] for r in steps_rows}
    cal_by_day    = {r['date_day']: r['v'] for r in cal_rows}
    stand_by_day  = {r['date_day']: r['v'] for r in stand_rows}
    ex_by_day     = {r['date_day']: r['v'] for r in ex_rows}

    total_steps = sum(v for v in steps_by_day.values())

    # Distancia total y por día (para ventanas temporales)
    with get_conn() as conn:
        dist_rows = conn.execute(
            "SELECT date_day, value, unit FROM records "
            "WHERE type='HKQuantityTypeIdentifierDistanceWalkingRunning' "
            "AND value IS NOT NULL ORDER BY date_day"
        ).fetchall()
    dist_by_day2 = defaultdict(float)
    for r in dist_rows:
        if r['date_day']:
            v = float(r['value'] or 0)
            u = (r['unit'] or '').lower()
            km = v if u in ('km','kilometer','kilometers') else v/1000
            dist_by_day2[r['date_day']] += km
    total_dist_km = sum(dist_by_day2.values())

    # Entrenamientos
    from services.workout import list_workouts
    wk_list  = list_workouts()
    total_wk = len(wk_list)

    # Distancia máxima en ventana de 7 días / mes / año
    sorted_days = sorted(d for d in dist_by_day2.keys() if d)


    def _max_dist_window(window):
        best = 0.0; best_date = None
        for i, d in enumerate(sorted_days):
            start = datetime.strptime(d, '%Y-%m-%d')
            end   = start + timedelta(days=window)
            total = sum(dist_by_day2.get(d2, 0) for d2 in sorted_days[i:]
                        if datetime.strptime(d2,'%Y-%m-%d') < end)
            if total > best:
                best = total; best_date = d
        return round(best, 2), best_date

    def _dist_by_period(fmt):
        by_p = defaultdict(float)
        for d, v in dist_by_day2.items():
            if d:
                try: by_p[datetime.strptime(d,'%Y-%m-%d').strftime(fmt)] += v
                except: pass
        return by_p

    max_week_dist,  max_week_date  = _max_dist_window(7)
    month_dist_map = _dist_by_period('%Y-%m')
    year_dist_map  = _dist_by_period('%Y')
    best_month_dist  = max(month_dist_map.values(), default=0)
    best_month_date  = max(month_dist_map, key=month_dist_map.get, default=None)
    best_year_dist   = max(year_dist_map.values(), default=0)
    best_year_date   = max(year_dist_map, key=year_dist_map.get, default=None)

    # Día que completó todos los anillos
    all_days = sorted(set(steps_by_day) | set(cal_by_day) | set(stand_by_day))
    rings_days = [
        d for d in all_days
        if (steps_by_day.get(d, 0) >= steps_goal and
            cal_by_day.get(d, 0)   >= cal_goal    and
            ex_by_day.get(d, 0)    >= ex_goal      and
            stand_by_day.get(d, 0) >= stand_goal)
    ]
    move_goal_days = [d for d in all_days if steps_by_day.get(d, 0) >= steps_goal]

    # Rachas de pasos >= goal (para semana/mes/año perfecto)
    def _count_streaks_of(date_list, min_len):
        """Cuenta cuántas rachas consecutivas de min_len o más hay."""
        count = 0; cur = 0; last_streak_end = None
        dates_set = set(date_list)
        all_d = sorted(all_days)
        for d in all_d:
            if d in dates_set:
                cur += 1
                if cur >= min_len:
                    if cur == min_len:
                        count += 1
                        last_streak_end = d
            else:
                cur = 0
        return count, last_streak_end

    week_steps_count, week_steps_last   = _count_streaks_of(move_goal_days, 7)
    week_stand_count, week_stand_last   = _count_streaks_of(
        [d for d in all_days if stand_by_day.get(d,0) >= stand_goal], 7
    )
    month_steps_count, month_steps_last = _count_streaks_of(move_goal_days, 28)
    year_steps_count,  year_steps_last  = _count_streaks_of(move_goal_days, 365)

    # Días con X% del objetivo de pasos
    def _days_above_pct(pct):
        threshold = steps_goal * pct
        days = [d for d, v in steps_by_day.items() if v >= threshold]
        return len(days), max(days) if days else None

    # Calorías >= 500 por día
    kcal_days = [d for d, v in cal_by_day.items() if v >= 500]

    # Pasos en un día >= threshold
    def _days_above_steps(threshold):
        days = sorted([d for d, v in steps_by_day.items() if v >= threshold])
        return len(days), days[-1] if days else None

    # Calcular condiciones para cada logro
    stats = {
        'rings_complete':    (len(rings_days),        rings_days[-1] if rings_days else None),
        'move_goal':         (len(move_goal_days),     move_goal_days[-1] if move_goal_days else None),
        'move_pct_2':        _days_above_pct(2.0),
        'move_pct_3':        _days_above_pct(3.0),
        'move_pct_4':        _days_above_pct(4.0),
        'calories_day':      (len(kcal_days),          kcal_days[-1] if kcal_days else None),
        'streak_steps_week_7':   (week_steps_count,  week_steps_last),
        'streak_stand_week_7':   (week_stand_count,  week_stand_last),
        'streak_steps_week_28':  (month_steps_count, month_steps_last),
        'streak_steps_week_365': (year_steps_count,  year_steps_last),
        'steps_day_10k':     _days_above_steps(10_000),
        'steps_day_20k':     _days_above_steps(20_000),
        'steps_day_30k':     _days_above_steps(30_000),
        'workouts_total':    (total_wk, wk_list[-1].get('date') if wk_list else None),
        'dist_total_1000':   (1 if total_dist_km >= 1000 else 0,
                              today if total_dist_km >= 1000 else None),
        'dist_week':         (max_week_dist,  max_week_date),
        'dist_month':        (best_month_dist, best_month_date),
        'dist_year':         (best_year_dist,  best_year_date),
        'dist_total_800':    (1 if total_dist_km >= 800 else 0,   today if total_dist_km >= 800 else None),
        'dist_total_1200':   (1 if total_dist_km >= 1200 else 0,  today if total_dist_km >= 1200 else None),
        'dist_total_10000':  (1 if total_dist_km >= 10000 else 0, today if total_dist_km >= 10000 else None),
        'dist_total_40075':  (1 if total_dist_km >= 40075 else 0, today if total_dist_km >= 40075 else None),
        'dist_total_384400': (1 if total_dist_km >= 384400 else 0,today if total_dist_km >= 384400 else None),
        'steps_total_1k':    (1 if total_steps >= 1_000 else 0,      today if total_steps >= 1_000 else None),
        'steps_total_100k':  (1 if total_steps >= 100_000 else 0,    today if total_steps >= 100_000 else None),
        'steps_total_1M':    (1 if total_steps >= 1_000_000 else 0,  today if total_steps >= 1_000_000 else None),
        'steps_total_5M':    (1 if total_steps >= 5_000_000 else 0,  today if total_steps >= 5_000_000 else None),
        'steps_total_10M':   (1 if total_steps >= 10_000_000 else 0, today if total_steps >= 10_000_000 else None),
        'steps_total_50M':   (1 if total_steps >= 50_000_000 else 0, today if total_steps >= 50_000_000 else None),
    }

    def _get_stat(ach_type, threshold):
        """Devuelve (count_achieved, last_date, value) para un logro."""
        if ach_type == 'rings_complete':
            n, last = stats['rings_complete']
            return n >= threshold, n, last
        elif ach_type == 'move_goal':
            n, last = stats['move_goal']
            return n >= threshold, n, last
        elif ach_type == 'move_pct':
            key = f'move_pct_{int(threshold)}'
            n, last = stats.get(key, (0, None))
            return n >= 1, n, last
        elif ach_type == 'calories_day':
            n, last = stats['calories_day']
            return n >= 1, n, last
        elif ach_type == 'streak_steps_week':
            key = f'streak_steps_week_{threshold}'
            n, last = stats.get(key, (0, None))
            return n >= 1, n, last
        elif ach_type == 'streak_stand_week':
            key = f'streak_stand_week_{threshold}'
            n, last = stats.get(key, (0, None))
            return n >= 1, n, last
        elif ach_type == 'steps_day':
            n, last = stats.get(f'steps_day_{int(threshold)}k' if threshold < 100000
                                else f'steps_day_{int(threshold)}', (0, None))
            # fallback
            if not n:
                t = int(threshold)
                n, last = _days_above_steps(t)
            return n >= 1, n, last
        elif ach_type == 'workouts_total':
            n, last = stats['workouts_total']
            return n >= threshold, n, last
        elif ach_type == 'steps_total':
            key = f'steps_total_{_fmt_threshold(threshold)}'
            met, last = stats.get(key, (0, None))
            return bool(met), int(total_steps), last
        elif ach_type == 'dist_total':
            key = f'dist_total_{int(threshold)}'
            met, last = stats.get(key, (0, None))
            return bool(met), round(total_dist_km, 1), last
        elif ach_type == 'dist_week':
            dist, last = stats.get('dist_week', (0, None))
            return dist >= threshold, round(dist, 1), last
        elif ach_type == 'dist_month':
            dist, last = stats.get('dist_month', (0, None))
            return dist >= threshold, round(dist, 1), last
        elif ach_type == 'dist_year':
            dist, last = stats.get('dist_year', (0, None))
            return dist >= threshold, round(dist, 1), last
        return False, 0, None

    def _fmt_threshold(t):
        if t >= 1_000_000: return f'{int(t//1_000_000)}M'
        if t >= 1_000:     return f'{int(t//1_000)}k'
        return str(int(t))

    # Leer logros guardados
    with get_conn() as conn:
        saved = {r['key']: r for r in
                 conn.execute("SELECT * FROM achievements").fetchall()}

    result = []
    with get_conn() as conn:
        for ach in ACHIEVEMENTS_DEF:
            key       = ach['key']
            ach_type  = ach['type']
            threshold = ach['threshold']
            count_mode = ach.get('count_mode', False)

            met, count_val, last_date = _get_stat(ach_type, threshold)

            # Guardar si se desbloqueó por primera vez
            if met and key not in saved:
                conn.execute(
                    "INSERT OR IGNORE INTO achievements (key,unlocked,unlock_date,value) VALUES (?,1,?,?)",
                    (key, last_date or today, count_val)
                )
            elif met:
                # Actualizar fecha y valor si count aumentó
                conn.execute(
                    "UPDATE achievements SET unlocked=1, unlock_date=?, value=? WHERE key=?",
                    (last_date or today, count_val, key)
                )

            # Obtener datos guardados
            row = saved.get(key)
            stored_count = int(row['value']) if row and row['value'] else 0
            final_count  = max(count_val, stored_count) if count_mode else count_val

            result.append({
                **{k: v for k, v in ach.items()},
                'unlocked':    met,
                'unlock_date': (row['unlock_date'] if row else None) or (last_date if met else None),
                'count':       int(final_count) if count_mode else None,
                'value':       int(count_val),
            })
        conn.commit()

    return result


def get_monthly_challenge(month=None):
    if not month:
        month = datetime.now().strftime('%Y-%m')
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM challenges WHERE month=?", (month,)).fetchall()
    return {'month': month, 'challenges': [dict(r) for r in rows]}


def save_monthly_challenge(month, challenges):
    with get_conn() as conn:
        conn.execute("DELETE FROM challenges WHERE month=?", (month,))
        for c in challenges:
            conn.execute(
                "INSERT INTO challenges (month,key,target,unit,label) VALUES (?,?,?,?,?)",
                (month, c['key'], c['target'], c['unit'], c['label'])
            )
        conn.commit()


def get_challenge_progress(month=None):
    if not month:
        month = datetime.now().strftime('%Y-%m')
    if not DB_FILE.exists():
        return []
    chal = get_monthly_challenge(month)
    if not chal['challenges']:
        return []

    goals     = get_user_goals()
    import calendar
    y, m      = int(month[:4]), int(month[5:7])
    _, last_d = calendar.monthrange(y, m)
    date_from = f'{month}-01'
    date_to   = min(f'{month}-{last_d:02d}', datetime.now().strftime('%Y-%m-%d'))

    result = []
    with get_conn() as conn:
        for c in chal['challenges']:
            val = 0
            key = c['key']
            if key == 'steps':
                r = conn.execute("SELECT SUM(value) FROM records WHERE type='HKQuantityTypeIdentifierStepCount' AND date_day>=? AND date_day<=?", (date_from,date_to)).fetchone()
                val = float(r[0] or 0)
            elif key == 'distance':
                rows = conn.execute("SELECT value,unit FROM records WHERE type='HKQuantityTypeIdentifierDistanceWalkingRunning' AND date_day>=? AND date_day<=?", (date_from,date_to)).fetchall()
                val = sum(float(r['value'] or 0) if (r['unit'] or '').lower() in ('km','kilometer') else float(r['value'] or 0)/1000 for r in rows)
            elif key == 'calories':
                r = conn.execute("SELECT SUM(value) FROM records WHERE type='HKQuantityTypeIdentifierActiveEnergyBurned' AND date_day>=? AND date_day<=?", (date_from,date_to)).fetchone()
                val = float(r[0] or 0)
            elif key == 'sleep_nights':
                rows = conn.execute(
                    "SELECT substr(end_date,1,10) as g, SUM(CAST((julianday(substr(end_date,1,19))-julianday(substr(start_date,1,19)))*1440 AS INTEGER)) as v "
                    "FROM records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' AND date_day>=? AND date_day<=? "
                    "AND value_str NOT LIKE '%InBed%' AND value_str NOT LIKE '%Awake%' GROUP BY g",
                    (date_from, date_to)
                ).fetchall()
                val = sum(1 for r in rows if r['v'] and r['v'] >= float(c.get('target',7))*60)
            elif key == 'workouts':
                from services.workout import list_workouts
                val = len([w for w in list_workouts() if date_from <= (w.get('date') or '') <= date_to])
            pct = min(100, round(val / float(c['target']) * 100, 1)) if c['target'] else 0
            result.append({**dict(c), 'current': round(val,1), 'pct': pct, 'done': pct >= 100})
    return result


def get_global_stats() -> dict:
    """Estadísticas globales de toda la vida del usuario."""
    if not DB_FILE.exists():
        return {}
    with get_conn() as conn:
        def _sum(hk_type):
            r = conn.execute(f"SELECT SUM(value) FROM records WHERE type=?", (hk_type,)).fetchone()
            return float(r[0] or 0)
        def _sum_km():
            rows = conn.execute(
                "SELECT value, unit FROM records WHERE type='HKQuantityTypeIdentifierDistanceWalkingRunning' AND value IS NOT NULL"
            ).fetchall()
            return sum(float(r['value'] or 0) if (r['unit'] or '').lower() in ('km','kilometer','kilometers') else float(r['value'] or 0)/1000 for r in rows)
        def _sleep_h():
            rows = conn.execute(
                "SELECT SUM(CAST((julianday(substr(end_date,1,19))-julianday(substr(start_date,1,19)))*60 AS INTEGER)) as v "
                "FROM records WHERE type='HKCategoryTypeIdentifierSleepAnalysis' "
                "AND value_str NOT LIKE '%InBed%' AND value_str NOT LIKE '%Awake%'"
            ).fetchone()
            return round(float(rows[0] or 0) / 60, 1)  # minutos → horas
        def _weight_range():
            r = conn.execute(
                "SELECT MIN(value), MAX(value) FROM records WHERE type='HKQuantityTypeIdentifierBodyMass' AND value > 0"
            ).fetchone()
            return round(float(r[0] or 0), 1), round(float(r[1] or 0), 1)
        def _workout_hours():
            r = conn.execute(
                "SELECT SUM(value) FROM records WHERE type='HKQuantityTypeIdentifierAppleExerciseTime'"
            ).fetchone()
            return round(float(r[0] or 0) / 60, 1)

        total_steps = int(_sum('HKQuantityTypeIdentifierStepCount'))
        total_dist  = round(_sum_km(), 1)
        total_floors= int(_sum('HKQuantityTypeIdentifierFlightsClimbed'))
        total_cal   = int(_sum('HKQuantityTypeIdentifierActiveEnergyBurned'))
        total_sleep = _sleep_h()
        w_min, w_max= _weight_range()
        total_ex_h  = _workout_hours()
        n_days      = conn.execute("SELECT COUNT(DISTINCT date_day) FROM records WHERE date_day!=''").fetchone()[0]

    from services.workout import list_workouts
    wk_list = list_workouts()
    total_wk = len(wk_list)
    total_wk_km = round(sum(float(w.get('distance_km') or 0) for w in wk_list), 1)

    return {
        'total_steps':   total_steps,
        'total_dist_km': total_dist,
        'total_floors':  total_floors,
        'total_cal':     total_cal,
        'total_sleep_h': total_sleep,
        'weight_min':    w_min,
        'weight_max':    w_max,
        'total_ex_h':    total_ex_h,
        'total_workouts': total_wk,
        'total_wk_km':   total_wk_km,
        'days_with_data': n_days,
    }
