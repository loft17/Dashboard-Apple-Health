"""
services/db.py — SQLite backend para Apple Health Dashboard
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager

DATA_DIR   = Path('data')
DB_FILE    = DATA_DIR / 'health.db'
STATS_FILE = DATA_DIR / 'stats.json'

# ── Tipos HealthKit ───────────────────────────────────────────────────────────
STEP_TYPES       = {'HKQuantityTypeIdentifierStepCount'}
DISTANCE_TYPES   = {'HKQuantityTypeIdentifierDistanceWalkingRunning',
                    'HKQuantityTypeIdentifierDistanceCycling',
                    'HKQuantityTypeIdentifierDistanceSwimming'}
ACTIVE_CAL_TYPES = {'HKQuantityTypeIdentifierActiveEnergyBurned'}
BASAL_CAL_TYPES  = {'HKQuantityTypeIdentifierBasalEnergyBurned'}
HEART_RATE_TYPES = {'HKQuantityTypeIdentifierHeartRate'}
SLEEP_TYPES      = {'HKCategoryTypeIdentifierSleepAnalysis'}

# Fases de sueño — valor string que viene del XML
SLEEP_DEEP  = {'HKCategoryValueSleepAnalysisAsleepDeep'}
SLEEP_REM   = {'HKCategoryValueSleepAnalysisAsleepREM'}
SLEEP_LIGHT = {'HKCategoryValueSleepAnalysisAsleepCore',
               'HKCategoryValueSleepAnalysisAsleep'}  # legacy
SLEEP_INBED = {'HKCategoryValueSleepAnalysisInBed'}


# ── Conexión ──────────────────────────────────────────────────────────────────
@contextmanager
def get_conn():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=30)
    conn.row_factory = sqlite3.Row
    # WAL mode: lecturas sin bloquear escrituras
    conn.execute("PRAGMA journal_mode=WAL")
    # Cache 64MB (default es 2MB — mejora queries complejas)
    conn.execute("PRAGMA cache_size=-65536")
    # Sync más rápido (seguro para datos de salud)
    conn.execute("PRAGMA synchronous=NORMAL")
    # Tablas temporales en RAM
    conn.execute("PRAGMA temp_store=MEMORY")
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    """Crea/migra el esquema. Seguro llamarlo siempre al arrancar."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS records (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                type        TEXT    NOT NULL,
                value       REAL,
                value_str   TEXT,
                unit        TEXT,
                start_date  TEXT    NOT NULL,
                end_date    TEXT,
                source_name TEXT,
                date_day    TEXT    GENERATED ALWAYS AS (substr(start_date, 1, 10)) STORED
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_dedup
                ON records (type, start_date);
            CREATE INDEX IF NOT EXISTS idx_day
                ON records (date_day);
            CREATE INDEX IF NOT EXISTS idx_type_day
                ON records (type, date_day);
            CREATE INDEX IF NOT EXISTS idx_type_day_val
                ON records (type, date_day, value);
            ANALYZE;
        """)
        # Tabla de gamificación
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS streaks (
                id       INTEGER PRIMARY KEY,
                key      TEXT UNIQUE,   -- 'steps_7k', 'sleep_7h', etc.
                current  INTEGER DEFAULT 0,
                best     INTEGER DEFAULT 0,
                last_date TEXT
            );
            CREATE TABLE IF NOT EXISTS achievements (
                id         INTEGER PRIMARY KEY,
                key        TEXT UNIQUE,
                unlocked   INTEGER DEFAULT 0,
                unlock_date TEXT,
                value      REAL
            );
            CREATE TABLE IF NOT EXISTS user_goals (
                key   TEXT PRIMARY KEY,
                value REAL NOT NULL
            );
            INSERT OR IGNORE INTO user_goals (key,value) VALUES ('steps_daily', 10000);
            INSERT OR IGNORE INTO user_goals (key,value) VALUES ('calories_daily', 500);
            INSERT OR IGNORE INTO user_goals (key,value) VALUES ('exercise_min', 30);
            INSERT OR IGNORE INTO user_goals (key,value) VALUES ('stand_hours', 12);
            CREATE TABLE IF NOT EXISTS custom_achievements (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                emoji       TEXT    DEFAULT '🎯',
                label       TEXT    NOT NULL,
                desc        TEXT,
                target_type TEXT,   -- 'steps','sleep_h','workout_km','manual'
                target_val  REAL,
                unlocked    INTEGER DEFAULT 0,
                unlock_date TEXT,
                created_at  TEXT    DEFAULT (date('now'))
            );
            CREATE TABLE IF NOT EXISTS challenges (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                month      TEXT,   -- 'YYYY-MM'
                key        TEXT,
                target     REAL,
                unit       TEXT,
                label      TEXT
            );
        """)

        # Migración: añadir value_str si no existe (BDs antiguas)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(records)").fetchall()]
        if 'value_str' not in cols:
            conn.execute("ALTER TABLE records ADD COLUMN value_str TEXT")
            conn.commit()


# ── Escritura ─────────────────────────────────────────────────────────────────
def insert_records(records: list[dict]) -> tuple[int, int]:
    if not records:
        return 0, 0

    rows = []
    for r in records:
        raw = r.get('value')
        num = _to_float(raw)
        # Si no es numérico, guardarlo como string
        val_str = str(raw) if raw is not None and num is None else None
        rows.append((
            r['type'], num, val_str, r.get('unit', ''),
            r['startDate'], r.get('endDate', ''), r.get('sourceName', '')
        ))

    with get_conn() as conn:
        before = conn.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        conn.executemany(
            'INSERT OR IGNORE INTO records '
            '(type, value, value_str, unit, start_date, end_date, source_name) '
            'VALUES (?,?,?,?,?,?,?)',
            rows
        )
        conn.commit()
        after = conn.execute('SELECT COUNT(*) FROM records').fetchone()[0]

    inserted = after - before
    return inserted, len(records) - inserted


def _to_float(val) -> float | None:
    try:
        return float(val) if val not in (None, '', 'null') else None
    except (ValueError, TypeError):
        return None


# ── Stats ─────────────────────────────────────────────────────────────────────
def load_stats() -> dict | None:
    """Carga stats con aliases normalizados para compatibilidad con templates."""
    if not DB_FILE.exists():
        return None
    # Siempre reconstruir para tener datos frescos (rápido, usa índices)
    try:
        with get_conn() as conn:
            total  = conn.execute('SELECT COUNT(*) FROM records').fetchone()[0]
            n_days = conn.execute(
                'SELECT COUNT(DISTINCT date_day) FROM records WHERE date_day != ""'
            ).fetchone()[0]
            dates  = conn.execute(
                'SELECT MIN(date_day), MAX(date_day) FROM records WHERE date_day != ""'
            ).fetchone()
            n_src  = conn.execute(
                'SELECT COUNT(DISTINCT source_name) FROM records'
            ).fetchone()[0]
        d_min, d_max = (dates[0] or ''), (dates[1] or '')
        # Leer fecha de última importación del stats.json si existe
        last_import = None
        if STATS_FILE.exists():
            try:
                s = json.load(open(STATS_FILE))
                last_import = s.get('last_import') or s.get('last_sync')
            except Exception:
                pass
        return {
            'record_count':  total,
            'day_count':     n_days,
            'first_date':    d_min,
            'last_date':     d_max,
            'last_import':   last_import,
            'source_count':  n_src,
            # aliases legacy
            'total_records': total,
            'date_min':      d_min,
            'date_max':      d_max,
        }
    except Exception:
        return None


def save_stats(stats: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = STATS_FILE.with_suffix('.tmp')
    with open(tmp, 'w') as f:
        json.dump(stats, f, indent=2)
    tmp.replace(STATS_FILE)


def rebuild_stats() -> dict:
    with get_conn() as conn:
        total   = conn.execute('SELECT COUNT(*) FROM records').fetchone()[0]
        n_types = conn.execute('SELECT COUNT(DISTINCT type) FROM records').fetchone()[0]
        dates   = conn.execute(
            'SELECT MIN(date_day), MAX(date_day) FROM records WHERE date_day != ""'
        ).fetchone()
        top = conn.execute(
            'SELECT type, COUNT(*) n FROM records GROUP BY type ORDER BY n DESC LIMIT 10'
        ).fetchall()

    d_min, d_max = (dates[0] or ''), (dates[1] or '')
    days = 0
    if d_min and d_max:
        days = (datetime.strptime(d_max, '%Y-%m-%d') -
                datetime.strptime(d_min, '%Y-%m-%d')).days

    stats = {
        'total_records':   total,
        'metrics_count':   n_types,
        'date_range_days': days,
        'date_min':        d_min,
        'date_max':        d_max,
        'last_sync':       datetime.now().strftime('%d/%m/%y'),
        'last_import':     datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
        'top_types':       [[r['type'], r['n']] for r in top],
    }
    save_stats(stats)
    return stats


# ── Helpers internos ──────────────────────────────────────────────────────────
def _sum_numeric(date_str: str, types: set[str]) -> float:
    if not DB_FILE.exists():
        return 0.0
    placeholders = ','.join('?' * len(types))
    with get_conn() as conn:
        row = conn.execute(
            f'SELECT COALESCE(SUM(value),0) FROM records '
            f'WHERE type IN ({placeholders}) AND date_day=?',
            (*types, date_str)
        ).fetchone()
    return row[0] if row else 0.0


def _parse_dt(s: str) -> datetime | None:
    for fmt in ('%Y-%m-%d %H:%M:%S %z', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _interval_minutes(start: str, end: str) -> float:
    s, e = _parse_dt(start), _parse_dt(end)
    if s and e:
        return (e - s).total_seconds() / 60
    return 0.0


# ── Objetivos del usuario ────────────────────────────────────────────────────
def get_user_goals() -> dict:
    if not DB_FILE.exists():
        return {'steps_daily': 10000, 'calories_daily': 500, 'exercise_min': 30, 'stand_hours': 12}
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM user_goals").fetchall()
    return {r['key']: r['value'] for r in rows} if rows else {'steps_daily': 10000, 'calories_daily': 500, 'exercise_min': 30, 'stand_hours': 12}

def save_user_goals(goals: dict):
    with get_conn() as conn:
        for k, v in goals.items():
            conn.execute("INSERT OR REPLACE INTO user_goals (key,value) VALUES (?,?)", (k, v))
        conn.commit()

# ── BATCH: todas las métricas del día en UNA conexión ────────────────────────
def get_day_data_batch(date_str: str) -> dict:
    """
    Reemplaza 9 llamadas individuales con una sola conexión SQLite.
    Recoge todos los registros del día en una query y los procesa en Python.
    """
    if not DB_FILE.exists():
        return {}

    # Tipos que necesitamos del día
    TYPES_NEEDED = (
        'HKQuantityTypeIdentifierStepCount',
        'HKQuantityTypeIdentifierDistanceWalkingRunning',
        'HKQuantityTypeIdentifierActiveEnergyBurned',
        'HKQuantityTypeIdentifierBasalEnergyBurned',
        'HKQuantityTypeIdentifierHeartRate',
        'HKQuantityTypeIdentifierHeartRateVariabilitySDNN',
        'HKQuantityTypeIdentifierRestingHeartRate',
        'HKQuantityTypeIdentifierAppleExerciseTime',
        'HKQuantityTypeIdentifierAppleStandHour',
        'HKQuantityTypeIdentifierAppleStandTime',
        'HKQuantityTypeIdentifierFlightsClimbed',
        'HKQuantityTypeIdentifierVO2Max',
        'HKQuantityTypeIdentifierOxygenSaturation',
        'HKQuantityTypeIdentifierRespiratoryRate',
        'HKQuantityTypeIdentifierWalkingStepLength',
        'HKQuantityTypeIdentifierWalkingSpeed',
        'HKQuantityTypeIdentifierBodyMass',
        'HKCategoryTypeIdentifierSleepAnalysis',
    )
    ph = ','.join('?' * len(TYPES_NEEDED))

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT type, value, value_str, unit, source_name, "
            f"start_date, end_date "
            f"FROM records WHERE type IN ({ph}) AND date_day=? "
            f"ORDER BY start_date",
            (*TYPES_NEEDED, date_str)
        ).fetchall()

    # Agrupar por tipo
    by_type: dict = {}
    for r in rows:
        t = r['type']
        if t not in by_type:
            by_type[t] = []
        by_type[t].append(r)

    result = {}

    # ── Pasos (priorizar Apple Watch sobre iPhone) ────────────────────────────
    step_rows = by_type.get('HKQuantityTypeIdentifierStepCount', [])
    if step_rows:
        by_src: dict = {}
        for r in step_rows:
            src = (r['source_name'] or 'unknown').strip()
            by_src[src] = by_src.get(src, 0.0) + (r['value'] or 0.0)
        def _prio(s):
            sl = s.lower()
            return 0 if 'watch' in sl else (1 if 'iphone' in sl else 2)
        result['steps'] = int(by_src[min(by_src, key=_prio)])
        # Serie por hora (mejor fuente)
        best_src = min(by_src, key=_prio)
        best_rows = [r for r in step_rows if (r['source_name'] or 'unknown').strip() == best_src]
        hourly_steps = {}
        for r in best_rows:
            try: h = int(r['start_date'][11:13])
            except: h = 0
            hourly_steps[h] = hourly_steps.get(h, 0) + (r['value'] or 0)
        result['steps_series'] = [{'h': h, 'v': round(v)} for h, v in sorted(hourly_steps.items())]
    else:
        result['steps'] = 0
        result['steps_series'] = []

    # ── Distancia ─────────────────────────────────────────────────────────────
    dist_rows = by_type.get('HKQuantityTypeIdentifierDistanceWalkingRunning', [])
    total_dist = 0.0
    for r in dist_rows:
        v = r['value'] or 0.0
        u = (r['unit'] or '').lower()
        total_dist += v if u in ('km','kilometer','kilometers') else v / 1000.0
    result['distance_km'] = round(total_dist, 2)

    # ── Calorías activas ──────────────────────────────────────────────────────
    cal_rows = by_type.get('HKQuantityTypeIdentifierActiveEnergyBurned', [])
    result['calories'] = int(sum(r['value'] or 0 for r in cal_rows))

    # ── Serie horaria calorías ────────────────────────────────────────────────
    hourly_cal: dict = {}
    for r in cal_rows:
        try:
            h = int(r['start_date'][11:13])
            hourly_cal[h] = hourly_cal.get(h, 0.0) + (r['value'] or 0.0)
        except Exception:
            pass
    result['cal_series'] = [{'h': h, 'v': round(v, 1)} for h, v in sorted(hourly_cal.items())]

    # ── Frecuencia cardíaca ───────────────────────────────────────────────────
    hr_rows = by_type.get('HKQuantityTypeIdentifierHeartRate', [])
    if hr_rows:
        vals = [r['value'] for r in hr_rows if r['value']]
        if vals:
            # Agrupar por hora para la gráfica (series con clave h y v)
            by_hour = {}
            for r in hr_rows:
                if not r['value']: continue
                h = int(r['start_date'][11:13]) if len(r['start_date']) > 12 else 0
                if h not in by_hour: by_hour[h] = []
                by_hour[h].append(r['value'])
            series = [{'h': h,
                         'v':   round(sum(vs)/len(vs), 1),
                         'max': round(max(vs), 1),
                         'min': round(min(vs), 1)}
                      for h, vs in sorted(by_hour.items())]
            result['hr'] = {
                'current': round(vals[-1], 1),
                'avg': round(sum(vals)/len(vals), 1),
                'min': round(min(vals), 1),
                'max': round(max(vals), 1),
                'series': series,
                'raw': [{'t': r['start_date'][11:16], 'v': r['value']} for r in hr_rows if r['value']],
            }
        else:
            result['hr'] = {}
    else:
        result['hr'] = {}

    # ── HRV ──────────────────────────────────────────────────────────────────
    hrv_rows = by_type.get('HKQuantityTypeIdentifierHeartRateVariabilitySDNN', [])
    if hrv_rows:
        vals = [r['value'] for r in hrv_rows if r['value']]
        if vals:
            result['hrv'] = {
                'avg':    round(sum(vals)/len(vals), 1),
                'series': [{'v': round(v, 1)} for v in vals],
            }
        else:
            result['hrv'] = {}
    else:
        result['hrv'] = {}

    # ── FC reposo ─────────────────────────────────────────────────────────────
    fc_rest = by_type.get('HKQuantityTypeIdentifierRestingHeartRate', [])
    result['hr_reposo'] = round(fc_rest[-1]['value'], 1) if fc_rest and fc_rest[-1]['value'] else None

    # ── Ejercicio ─────────────────────────────────────────────────────────────
    ex_rows = by_type.get('HKQuantityTypeIdentifierAppleExerciseTime', [])
    result['ex_min'] = int(sum(r['value'] or 0 for r in ex_rows))

    # ── De pie ────────────────────────────────────────────────────────────────
    stand_rows = by_type.get('HKQuantityTypeIdentifierAppleStandHour', [])
    result['stand_h'] = len([r for r in stand_rows if (r['value_str'] or '').endswith('Stood')])

    # ── Pisos ─────────────────────────────────────────────────────────────────
    pisos_rows = by_type.get('HKQuantityTypeIdentifierFlightsClimbed', [])
    result['pisos'] = int(sum(r['value'] or 0 for r in pisos_rows))

    # ── VO2 max ───────────────────────────────────────────────────────────────
    vo2_rows = by_type.get('HKQuantityTypeIdentifierVO2Max', [])
    result['vo2'] = round(vo2_rows[-1]['value'], 1) if vo2_rows and vo2_rows[-1]['value'] else None

    # ── SpO2 ──────────────────────────────────────────────────────────────────
    spo2_rows = by_type.get('HKQuantityTypeIdentifierOxygenSaturation', [])
    if spo2_rows:
        vals = [r['value']*100 for r in spo2_rows if r['value']]
        result['spo2'] = round(sum(vals)/len(vals), 1) if vals else None
    else:
        result['spo2'] = None

    # ── Sueño ─────────────────────────────────────────────────────────────────
    # (sueño complejo — delegar a get_sleep_day que ya está optimizado)
    result['_needs_sleep'] = True

    return result


# ── Pasos (deduplicado por fuente) ────────────────────────────────────────────
def get_steps_for_day(date_str: str) -> int:
    if not DB_FILE.exists():
        return 0
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, source_name FROM records '
            'WHERE type=? AND date_day=?',
            ('HKQuantityTypeIdentifierStepCount', date_str)
        ).fetchall()
    if not rows:
        return 0
    by_src: dict[str, float] = {}
    for r in rows:
        src = (r['source_name'] or 'unknown').strip()
        by_src[src] = by_src.get(src, 0.0) + (r['value'] or 0.0)
    def prio(s):
        sl = s.lower()
        return 0 if 'watch' in sl else (1 if 'iphone' in sl else 2)
    return int(by_src[min(by_src, key=prio)])


# ── Distancia (respeta unidad km/m) ──────────────────────────────────────────
def get_distance_km(date_str: str) -> float:
    if not DB_FILE.exists():
        return 0.0
    ph = ','.join('?' * len(DISTANCE_TYPES))
    with get_conn() as conn:
        rows = conn.execute(
            f'SELECT value, unit FROM records '
            f'WHERE type IN ({ph}) AND date_day=?',
            (*DISTANCE_TYPES, date_str)
        ).fetchall()
    total = 0.0
    for r in rows:
        v = r['value'] or 0.0
        u = (r['unit'] or '').lower()
        total += v if u in ('km', 'kilometer', 'kilometers') else v / 1000.0
    return total


# ── Calorías activas ──────────────────────────────────────────────────────────
def get_calories(date_str: str) -> int:
    if not DB_FILE.exists():
        return 0
    return int(_sum_numeric(date_str, ACTIVE_CAL_TYPES))


# ── Serie horaria de calorías (para mini barras) ──────────────────────────────
def get_active_energy_series(date_str: str) -> list:
    if not DB_FILE.exists():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? ORDER BY start_date',
            ('HKQuantityTypeIdentifierActiveEnergyBurned', date_str)
        ).fetchall()
    hourly: dict[int, float] = {}
    for r in rows:
        try:
            h = int(r['start_date'][11:13])
            hourly[h] = hourly.get(h, 0.0) + (r['value'] or 0.0)
        except Exception:
            pass
    return [{'h': h, 'v': round(v, 1)} for h, v in sorted(hourly.items())]


# ── Frecuencia cardíaca ───────────────────────────────────────────────────────
def get_heart_rate_day(date_str: str) -> dict:
    if not DB_FILE.exists():
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? AND value IS NOT NULL ORDER BY start_date',
            ('HKQuantityTypeIdentifierHeartRate', date_str)
        ).fetchall()
    if not rows:
        return {}
    vals = [r['value'] for r in rows]
    # Serie: promedio por hora
    hourly: dict[int, list] = {}
    for r in rows:
        try:
            h = int(r['start_date'][11:13])
            hourly.setdefault(h, []).append(r['value'])
        except Exception:
            pass
    series = [{'h': h, 'v': round(sum(v)/len(v))} for h, v in sorted(hourly.items())]
    # Última medición del día como "actual"
    return {
        'current': int(vals[-1]),
        'avg':     int(sum(vals) / len(vals)),
        'min':     int(min(vals)),
        'max':     int(max(vals)),
        'series':  series,
    }


# ── HRV ───────────────────────────────────────────────────────────────────────
def get_hrv_day(date_str: str) -> dict:
    if not DB_FILE.exists():
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? AND value IS NOT NULL ORDER BY start_date',
            ('HKQuantityTypeIdentifierHeartRateVariabilitySDNN', date_str)
        ).fetchall()
    if not rows:
        return {}
    vals = [r['value'] for r in rows]
    series = [{'i': i, 'v': round(r['value'], 1)} for i, r in enumerate(rows)]
    return {'avg': round(sum(vals)/len(vals), 1), 'series': series}


# ── Sueño ─────────────────────────────────────────────────────────────────────
def get_sleep_day(date_str: str) -> dict:
    """
    Sueño de la noche que termina en date_str (el Watch graba la noche
    del día anterior → madrugada de date_str).
    value_str contiene el string de fase: HKCategoryValueSleepAnalysis*
    """
    if not DB_FILE.exists():
        return {}

    dt   = datetime.strptime(date_str, '%Y-%m-%d')
    prev = (dt - timedelta(days=1)).strftime('%Y-%m-%d')

    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value_str, start_date, end_date FROM records '
            'WHERE type=? AND (date_day=? OR date_day=?) '
            'AND value_str IS NOT NULL '
            'ORDER BY start_date',
            ('HKCategoryTypeIdentifierSleepAnalysis', prev, date_str)
        ).fetchall()

    if not rows:
        return {}

    deep_min = rem_min = light_min = 0.0

    # Parsear todos los segmentos
    all_segs = []
    for r in rows:
        vs   = r['value_str'] or ''
        mins = _interval_minutes(r['start_date'], r['end_date'])
        if mins <= 0:
            continue
        if 'AsleepDeep' in vs:
            phase = 'deep'
        elif 'AsleepREM' in vs:
            phase = 'rem'
        elif 'AsleepCore' in vs:
            phase = 'light'
        elif 'Asleep' in vs and 'InBed' not in vs:
            phase = 'light'
        elif 'Awake' in vs:
            phase = 'awake'
        else:
            continue  # InBed no cuenta
        all_segs.append({
            'phase': phase,
            'mins':  round(mins, 1),
            'start': r['start_date'],
            'end':   r['end_date'],
        })

    if not all_segs:
        return {}

    # Agrupar en sesiones (gap > 60 min = nueva sesión)
    sessions = []
    cur_session = [all_segs[0]]
    for seg in all_segs[1:]:
        gap = _interval_minutes(cur_session[-1]['end'], seg['start'])
        if gap > 60:
            sessions.append(cur_session)
            cur_session = [seg]
        else:
            cur_session.append(seg)
    sessions.append(cur_session)

    # Tomar la sesión más larga (sueño principal, no siestas cortas)
    def session_sleep_min(s):
        return sum(sg['mins'] for sg in s if sg['phase'] != 'awake')
    main_session = max(sessions, key=session_sleep_min)
    segments = main_session

    # Recalcular totales de la sesión principal
    for seg in segments:
        if seg['phase'] == 'deep':  deep_min  += seg['mins']
        elif seg['phase'] == 'rem': rem_min   += seg['mins']
        elif seg['phase'] == 'light': light_min += seg['mins']

    total_min = deep_min + rem_min + light_min
    if total_min == 0:
        return {}

    h = int(total_min // 60)
    m = int(total_min % 60)
    return {
        'total_str': f'{h}h {m:02d}m',
        'total_min': round(total_min),
        'deep_min':  round(deep_min),
        'rem_min':   round(rem_min),
        'light_min': round(light_min),
        'segments':  segments,
    }


# ── De pie ────────────────────────────────────────────────────────────────────
def get_stand_hours(date_str: str) -> int:
    """
    HKCategoryTypeIdentifierAppleStandHour: cada registro = 1 hora de pie.
    value es null (es una categoría), pero la PRESENCIA del registro indica
    que esa hora estuvo de pie. Contamos registros, no suma de value.
    """
    if not DB_FILE.exists():
        return 0
    with get_conn() as conn:
        row = conn.execute(
            'SELECT COUNT(*) FROM records '
            'WHERE type=? AND date_day=?',
            ('HKCategoryTypeIdentifierAppleStandHour', date_str)
        ).fetchone()
    return row[0] if row else 0


# ── Minutos de ejercicio ──────────────────────────────────────────────────────
def get_exercise_minutes(date_str: str) -> int:
    if not DB_FILE.exists():
        return 0
    return int(_sum_numeric(date_str, {'HKQuantityTypeIdentifierAppleExerciseTime'}))


# ── Entrenamientos ────────────────────────────────────────────────────────────
def get_workouts_day(date_str: str) -> list:
    if not DB_FILE.exists():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT type, value, unit, start_date, end_date FROM records "
            "WHERE type LIKE 'HKWorkout%' AND date_day=? ORDER BY start_date",
            (date_str,)
        ).fetchall()
    result = []
    for r in rows:
        dur = _interval_minutes(r['start_date'], r['end_date'])
        result.append({'type': r['type'], 'value': r['value'],
                       'unit': r['unit'], 'dur_min': int(dur)})
    return result[:5]


# ── Resumen del día (dashboard) ───────────────────────────────────────────────
def get_today_summary(date_str: str | None = None) -> dict | None:
    if not DB_FILE.exists():
        return None
    date_str = date_str or datetime.now().strftime('%Y-%m-%d')
    return {
        'date':        date_str,
        'steps':       get_steps_for_day(date_str),
        'distance_km': round(get_distance_km(date_str), 2),
        'calories':    get_calories(date_str),
    }


# ── Rango de fechas disponibles ───────────────────────────────────────────────
def get_available_dates() -> dict:
    if not DB_FILE.exists():
        return {}
    with get_conn() as conn:
        row = conn.execute(
            'SELECT MIN(date_day), MAX(date_day) FROM records WHERE date_day!=""'
        ).fetchone()
        # Último día con pasos reales
        last_steps = conn.execute(
            "SELECT MAX(date_day) FROM records "
            "WHERE type='HKQuantityTypeIdentifierStepCount' AND value>100 AND date_day!=''"
        ).fetchone()
    return {
        'date_min': row[0] or '',
        'date_max': row[1] or '',
        'last_with_steps': (last_steps[0] if last_steps else None) or row[1] or '',
    }


# ── Debug ─────────────────────────────────────────────────────────────────────
def debug_type_sample(type_str: str, limit: int = 5) -> list[dict]:
    if not DB_FILE.exists():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT type, value, value_str, unit, start_date, date_day '
            'FROM records WHERE type=? ORDER BY start_date DESC LIMIT ?',
            (type_str, limit)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Métricas adicionales ──────────────────────────────────────────────────────

def _avg_numeric(date_str: str, hk_type: str) -> float | None:
    if not DB_FILE.exists():
        return None
    with get_conn() as conn:
        row = conn.execute(
            'SELECT AVG(value) FROM records WHERE type=? AND date_day=? AND value IS NOT NULL',
            (hk_type, date_str)
        ).fetchone()
    v = row[0] if row else None
    return round(v, 1) if v is not None else None

def _last_numeric(date_str: str, hk_type: str) -> float | None:
    if not DB_FILE.exists():
        return None
    with get_conn() as conn:
        row = conn.execute(
            'SELECT value FROM records WHERE type=? AND date_day=? AND value IS NOT NULL '
            'ORDER BY start_date DESC LIMIT 1',
            (hk_type, date_str)
        ).fetchone()
    return round(row[0], 1) if row and row[0] is not None else None

def _count_records(date_str: str, hk_type: str) -> int:
    if not DB_FILE.exists():
        return 0
    with get_conn() as conn:
        row = conn.execute(
            'SELECT COUNT(*) FROM records WHERE type=? AND date_day=?',
            (hk_type, date_str)
        ).fetchone()
    return row[0] if row else 0

def _series_numeric(date_str: str, hk_type: str, limit: int = 48) -> list:
    if not DB_FILE.exists():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? AND value IS NOT NULL ORDER BY start_date LIMIT ?',
            (hk_type, date_str, limit)
        ).fetchall()
    return [{'i': i, 'v': round(r['value'], 1), 't': r['start_date'][11:16]}
            for i, r in enumerate(rows)]

def _steps_by_hour(date_str: str) -> list:
    """Pasos agrupados por hora del día, para la gráfica de barras."""
    if not DB_FILE.exists():
        return []
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? AND value IS NOT NULL ORDER BY start_date',
            ('HKQuantityTypeIdentifierStepCount', date_str)
        ).fetchall()
    hourly = {}
    for r in rows:
        try:
            h = int(r['start_date'][11:13])
            hourly[h] = hourly.get(h, 0) + r['value']
        except Exception:
            pass
    # Rellenar horas vacías con 0 entre la primera y la última con datos
    if not hourly:
        return []
    h_min, h_max = min(hourly), max(hourly)
    return [{'h': h, 'v': round(hourly.get(h, 0))} for h in range(h_min, h_max+1)]


def _spo2_stats(date_str: str) -> dict:
    """SpO2 en %, con min/max para el intervalo. Apple guarda en fracción (0.95 = 95%)."""
    if not DB_FILE.exists():
        return {}
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? AND value IS NOT NULL ORDER BY start_date',
            ('HKQuantityTypeIdentifierOxygenSaturation', date_str)
        ).fetchall()
    if not rows:
        return {}
    vals = [r['value'] * 100 for r in rows]   # fracción → porcentaje
    series = [{'i': i, 'v': round(r['value']*100, 1), 't': r['start_date'][11:16]}
              for i, r in enumerate(rows)]
    return {
        'avg':    round(sum(vals)/len(vals), 1),
        'min':    round(min(vals), 1),
        'max':    round(max(vals), 1),
        'series': series,
    }


def get_extra_metrics(date_str: str) -> dict:
    """Todas las métricas del panel secundario."""
    floors    = int(_sum_numeric(date_str, {'HKQuantityTypeIdentifierFlightsClimbed'}))
    spo2      = _spo2_stats(date_str)
    daylight  = _avg_numeric(date_str, 'HKQuantityTypeIdentifierTimeInDaylight')
    hr_walk   = _avg_numeric(date_str, 'HKQuantityTypeIdentifierWalkingHeartRateAverage')
    breath_dist = _avg_numeric(date_str, 'HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances')
    resp_rate = _avg_numeric(date_str, 'HKQuantityTypeIdentifierRespiratoryRate')
    wrist_temp= _avg_numeric(date_str, 'HKQuantityTypeIdentifierAppleSleepingWristTemperature')
    steadiness= _avg_numeric(date_str, 'HKQuantityTypeIdentifierAppleWalkingSteadiness')
    hr_recov  = _last_numeric(date_str, 'HKQuantityTypeIdentifierHeartRateRecoveryOneMinute')
    vo2max    = _last_numeric(date_str, 'HKQuantityTypeIdentifierVO2Max')
    noise_env    = _avg_numeric(date_str, 'HKQuantityTypeIdentifierEnvironmentalAudioExposure')
    noise_hp     = _avg_numeric(date_str, 'HKQuantityTypeIdentifierHeadphoneAudioExposure')
    wrist_temp   = _avg_numeric(date_str, 'HKQuantityTypeIdentifierAppleSleepingWristTemperature')
    breath_dist  = _avg_numeric(date_str, 'HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances')
    audio_events   = _count_records(date_str, 'HKCategoryTypeIdentifierAudioExposureEvent')
    # mindful_min se calcula en get_all_metrics directamente desde los registros del día
    water     = _sum_numeric(date_str, {'HKQuantityTypeIdentifierDietaryWater'})
    bmi       = _last_numeric(date_str, 'HKQuantityTypeIdentifierBodyMassIndex')
    handwash  = _count_records(date_str, 'HKCategoryTypeIdentifierHandwashingEvent')
    # ECG — solo contar si hay registros ese día
    ecg_count = _count_records(date_str, 'HKDataTypeECG')
    # Respiración nocturna — serie
    resp_series = _series_numeric(date_str, 'HKQuantityTypeIdentifierRespiratoryRate', 24)

    return {
        'floors':       floors or None,
        'spo2':         spo2,           # dict con avg/min/max/series
        'daylight_min': daylight,       # min
        'hr_walk':      hr_walk,        # PPM
        'breath_dist':  breath_dist,    # alteraciones/h
        'resp_rate':    resp_rate,      # rpm
        'wrist_temp':   wrist_temp,     # ºC
        'steadiness':   steadiness,     # %
        'hr_recov':     hr_recov,       # PPM
        'vo2max':       vo2max,         # mL/min·kg
        'noise_env':    noise_env,      # dB
        'noise_hp':     noise_hp,       # dB
        'water_ml':     int(water) if water else None,
        'bmi':          bmi,
        'handwash':     handwash or None,
        'ecg_count':    ecg_count or None,
        'resp_series':  resp_series,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PANEL COMPLETO — todas las métricas organizadas por categoría
# ═══════════════════════════════════════════════════════════════════════════════

def _metric(date_str: str, hk_type: str, agg: str = 'avg',
            multiplier: float = 1.0, decimals: int = 1) -> dict:
    """
    Devuelve un dict con value, min, max y series para un tipo HK.
    agg: 'avg' | 'sum' | 'last' | 'count'
    """
    if not DB_FILE.exists():
        return {'value': None, 'min': None, 'max': None, 'series': []}

    with get_conn() as conn:
        if agg == 'count':
            row = conn.execute(
                'SELECT COUNT(*) FROM records WHERE type=? AND date_day=?',
                (hk_type, date_str)
            ).fetchone()
            val = row[0] if row else 0
            return {'value': val if val else None, 'min': None, 'max': None, 'series': []}

        rows = conn.execute(
            'SELECT value, start_date FROM records '
            'WHERE type=? AND date_day=? AND value IS NOT NULL ORDER BY start_date',
            (hk_type, date_str)
        ).fetchall()

    if not rows:
        return {'value': None, 'min': None, 'max': None, 'series': []}

    vals = [r['value'] * multiplier for r in rows]

    if agg == 'sum':
        value = sum(vals)
    elif agg == 'last':
        value = vals[-1]
    elif agg == 'avg':
        value = sum(vals) / len(vals)
    else:
        value = vals[0]

    # Serie horaria (máx 48 puntos, agrupados por hora)
    hourly: dict[int, list] = {}
    for r in rows:
        try:
            h = int(r['start_date'][11:13])
            hourly.setdefault(h, []).append(r['value'] * multiplier)
        except Exception:
            pass
    series = [{'h': h, 'v': round(sum(v)/len(v), decimals)}
              for h, v in sorted(hourly.items())]

    return {
        'value':    round(value, decimals),
        'min':      round(min(vals), decimals),
        'max':      round(max(vals), decimals),
        'series':   series,
        'count':    len(vals),
    }


def get_all_metrics(date_str: str) -> dict:
    """
    Devuelve TODAS las métricas del día agrupadas por categoría.
    Solo consulta tipos que existen en la BD.
    """
    d = date_str

    # ── Actividad ──────────────────────────────────────────────────────────────
    actividad = {
        'pasos':          {**_metric(d, 'HKQuantityTypeIdentifierStepCount', 'sum', 1, 0),
                          'series': _steps_by_hour(d)},
        'cal_activas':    _metric(d, 'HKQuantityTypeIdentifierActiveEnergyBurned',   'sum', 1, 0),
        'cal_basales':    _metric(d, 'HKQuantityTypeIdentifierBasalEnergyBurned',    'sum', 1, 0),
        'distancia':      _metric(d, 'HKQuantityTypeIdentifierDistanceWalkingRunning','sum', 1, 2),
        'distancia_cicl': _metric(d, 'HKQuantityTypeIdentifierDistanceCycling',      'sum', 1, 2),
        'pisos':          _metric(d, 'HKQuantityTypeIdentifierFlightsClimbed',       'sum', 1, 0),
        'ejercicio_min':  _metric(d, 'HKQuantityTypeIdentifierAppleExerciseTime',    'sum', 1, 0),
        'de_pie_min':     _metric(d, 'HKQuantityTypeIdentifierAppleStandTime',       'sum', 1, 0),
        'de_pie_horas':   _metric(d, 'HKCategoryTypeIdentifierAppleStandHour',       'count'),
        'esfuerzo_fis':   _metric(d, 'HKQuantityTypeIdentifierPhysicalEffort',       'avg', 1, 2),
        'luz_diurna':     _metric(d, 'HKQuantityTypeIdentifierTimeInDaylight',       'sum', 1, 0),
    }

    # ── Corazón ────────────────────────────────────────────────────────────────
    corazon = {
        'fc':             {**_metric(d, 'HKQuantityTypeIdentifierHeartRate', 'avg', 1, 0),
                          'raw': _series_numeric(d, 'HKQuantityTypeIdentifierHeartRate', 2000)},
        'fc_reposo':      _metric(d, 'HKQuantityTypeIdentifierRestingHeartRate',        'avg', 1, 0),
        'fc_caminar':     _metric(d, 'HKQuantityTypeIdentifierWalkingHeartRateAverage', 'avg', 1, 0),
        'hrv':            _metric(d, 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN','avg', 1, 1),
        'fc_recuperacion':_metric(d, 'HKQuantityTypeIdentifierHeartRateRecoveryOneMinute','last',1, 0),
    }

    # ── Respiración y O₂ ──────────────────────────────────────────────────────
    respiracion = {
        'frec_resp':      _metric(d, 'HKQuantityTypeIdentifierRespiratoryRate',                  'avg', 1, 1),
        'spo2':           _metric(d, 'HKQuantityTypeIdentifierOxygenSaturation',                 'avg', 100, 1),  # fracción→%
        'spo2_min':       None,  # calculado abajo
        'spo2_max':       None,
        'alter_resp':     _metric(d, 'HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances','avg', 1, 1),
        'vo2max':         _metric(d, 'HKQuantityTypeIdentifierVO2Max',                           'last',1, 1),
    }
    # SpO2 min/max también en %
    spo2_raw = respiracion['spo2']
    if spo2_raw['min'] is not None:
        respiracion['spo2']['min'] = round(spo2_raw['min'], 1)
        respiracion['spo2']['max'] = round(spo2_raw['max'], 1)
        # Corregir series que ya vienen multiplicadas
        respiracion['spo2']['series'] = [
            {'h': s['h'], 'v': round(s['v'], 1)} for s in spo2_raw['series']
        ]

    # ── Marcha y movilidad ─────────────────────────────────────────────────────
    marcha = {
        'velocidad':      _metric(d, 'HKQuantityTypeIdentifierWalkingSpeed',               'avg', 1, 2),
        'longitud_zanca': _metric(d, 'HKQuantityTypeIdentifierWalkingStepLength',           'avg', 1, 1),
        'doble_apoyo':    _metric(d, 'HKQuantityTypeIdentifierWalkingDoubleSupportPercentage','avg',1, 1),
        'asimetria':      _metric(d, 'HKQuantityTypeIdentifierWalkingAsymmetryPercentage',  'avg', 1, 1),
        'estabilidad':    _metric(d, 'HKQuantityTypeIdentifierAppleWalkingSteadiness',      'avg', 100, 1),  # fracción→%
        'vel_subida':     _metric(d, 'HKQuantityTypeIdentifierStairAscentSpeed',            'avg', 1, 2),
        'vel_bajada':     _metric(d, 'HKQuantityTypeIdentifierStairDescentSpeed',           'avg', 1, 2),
        'test_6min':      _metric(d, 'HKQuantityTypeIdentifierSixMinuteWalkTestDistance',   'last',1, 0),
    }

    # ── Cuerpo — usa último valor disponible (pueden ser datos de días pasados) ──
    def _body_metric(hk_type: str, mult: float = 1.0, dec: int = 1) -> dict:
        """
        Busca el último registro de un tipo corporal en cualquier fecha <= date_str.
        Añade 'stale_date' si el dato no es de hoy, para mostrar advertencia.
        """
        if not DB_FILE.exists():
            return {'value': None, 'stale_date': None}
        with get_conn() as conn:
            row = conn.execute(
                'SELECT value, date_day FROM records '
                'WHERE type=? AND value IS NOT NULL AND date_day<=? '
                'ORDER BY date_day DESC, start_date DESC LIMIT 1',
                (hk_type, date_str)
            ).fetchone()
        if not row or row['value'] is None:
            return {'value': None, 'stale_date': None}
        stale = row['date_day'] if row['date_day'] != date_str else None
        return {
            'value':      round(row['value'] * mult, dec),
            'min':        None, 'max': None, 'series': [],
            'stale_date': stale,
        }

    cuerpo = {
        'peso':       _body_metric('HKQuantityTypeIdentifierBodyMass',           1,   1),
        'altura':     _body_metric('HKQuantityTypeIdentifierHeight',             1,   1),
        'imc':        _body_metric('HKQuantityTypeIdentifierBodyMassIndex',      1,   1),
        'grasa':      _body_metric('HKQuantityTypeIdentifierBodyFatPercentage',  100, 1),
        'masa_magra': _body_metric('HKQuantityTypeIdentifierLeanBodyMass',       1,   1),
        'cintura':    _body_metric('HKQuantityTypeIdentifierWaistCircumference', 1,   1),
    }

    # ── Sueño ──────────────────────────────────────────────────────────────────
    # get_sleep_day ya devuelve el resumen procesado
    sueño_raw = get_sleep_day(date_str)

    # ── Audio y mindfulness ──────────────────────────────────────────────────────
    # Calcular minutos de mindfulness para este día (query directa)
    _mindful_min = 0.0
    if DB_FILE.exists():
        with get_conn() as conn:
            # Calcular duración en SQL directamente con substr para evitar TZ
            row = conn.execute(
                "SELECT SUM(CAST((julianday(substr(end_date,1,19)) "
                "       - julianday(substr(start_date,1,19))) * 1440 AS REAL)) as mins "
                "FROM records WHERE type='HKCategoryTypeIdentifierMindfulSession' "
                "AND date_day=?",
                (date_str,)
            ).fetchone()
            _mindful_min = float(row['mins'] or 0)

    # Serie horaria de ruido ambiental (igual que FC del día)
    _noise_series = []
    if DB_FILE.exists():
        with get_conn() as conn:
            _nrows = conn.execute(
                "SELECT substr(start_date,12,5) as t, AVG(value) as v "
                "FROM records WHERE type='HKQuantityTypeIdentifierEnvironmentalAudioExposure' "
                "AND date_day=? AND value IS NOT NULL "
                "GROUP BY substr(start_date,1,13) ORDER BY start_date",
                (date_str,)
            ).fetchall()
            _noise_series = [{'t': r['t'], 'v': round(float(r['v']),1)} for r in _nrows if r['v']]

    # Serie horaria de auriculares
    _auri_series = []
    if DB_FILE.exists():
        with get_conn() as conn:
            _arows = conn.execute(
                "SELECT substr(start_date,12,5) as t, AVG(value) as v "
                "FROM records WHERE type='HKQuantityTypeIdentifierHeadphoneAudioExposure' "
                "AND date_day=? AND value IS NOT NULL "
                "GROUP BY substr(start_date,1,13) ORDER BY start_date",
                (date_str,)
            ).fetchall()
            _auri_series = [{'t': r['t'], 'v': round(float(r['v']),1)} for r in _arows if r['v']]

    _ruido_env_base  = _metric(d, 'HKQuantityTypeIdentifierEnvironmentalAudioExposure', 'avg', 1, 1)
    _ruido_auri_base = _metric(d, 'HKQuantityTypeIdentifierHeadphoneAudioExposure',     'avg', 1, 1)
    if _ruido_env_base:  _ruido_env_base['series']  = _noise_series
    if _ruido_auri_base: _ruido_auri_base['series'] = _auri_series

    audio = {
        'temp_muneca':      _metric(d, 'HKQuantityTypeIdentifierAppleSleepingWristTemperature', 'avg', 1, 2),
        'alter_resp_sleep': _metric(d, 'HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances', 'avg', 1, 1),
        'mindful_min':      {'value': round(_mindful_min, 1), 'unit': 'min'},
        'ruido_env':        _ruido_env_base  or {'value': None, 'series': []},
        'ruido_auri':       _ruido_auri_base or {'value': None, 'series': []},
        'eventos_audio':    _metric(d, 'HKCategoryTypeIdentifierAudioExposureEvent', 'count'),
    }

    # ── Temperatura (sueño) ────────────────────────────────────────────────────
    temp_muneca = _metric(d, 'HKQuantityTypeIdentifierAppleSleepingWristTemperature', 'avg', 1, 2)

    # ── Nutrición e higiene ────────────────────────────────────────────────────
    otros = {
        'agua':           _metric(d, 'HKQuantityTypeIdentifierDietaryWater',          'sum', 1, 0),
        'lavado_manos':   _metric(d, 'HKCategoryTypeIdentifierHandwashingEvent',       'count'),
    }

    return {
        'actividad':   actividad,
        'corazon':     corazon,
        'respiracion': respiracion,
        'marcha':      marcha,
        'cuerpo':      cuerpo,
        'sueno':       sueño_raw,
        'audio':       audio,
        # ánimo: eliminado — requiere registro manual iOS 17+
        'temp_muneca': temp_muneca,
        'otros':       otros,
    }


# ── Puntuación de recuperación y tendencia VO₂ ────────────────────────────────

def get_sleep_score(date_str: str) -> dict:
    """Puntuacion de sueño 0-100 basada en duracion, calidad, continuidad y respiracion."""
    sleep = get_sleep_day(date_str)
    if not sleep or not sleep.get('total_min', 0):
        return {}

    total_min = sleep.get('total_min', 0)
    total_h   = total_min / 60
    deep_min  = sleep.get('deep_min', 0) or 0
    rem_min   = sleep.get('rem_min',  0) or 0
    inbed_min = sleep.get('inbed_min', total_min) or total_min

    # Duracion (0-40 pts)
    dur_pts = 40 if total_h >= 7.5 else 35 if total_h >= 7.0 else 25 if total_h >= 6.0 else 15 if total_h >= 5.0 else 5

    # Calidad profundo+REM (0-35 pts)
    q = (deep_min + rem_min) / total_min * 100 if total_min else 0
    qual_pts = 35 if q >= 40 else 28 if q >= 30 else 20 if q >= 20 else 12 if q >= 10 else 5

    # Continuidad (0-15 pts)
    cont = total_min / inbed_min * 100 if inbed_min else 100
    cont_pts = 15 if cont >= 90 else 11 if cont >= 80 else 7

    # Respiracion (0-10 pts)
    breath = _avg_numeric(date_str, 'HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances')
    brth_pts = 10 if breath is None else 10 if breath < 5 else 6 if breath < 10 else 3 if breath < 20 else 0

    score = min(100, dur_pts + qual_pts + cont_pts + brth_pts)

    if score >= 85:   level, color = 'Excelente', '#34c759'
    elif score >= 70: level, color = 'Bueno',     '#30d158'
    elif score >= 55: level, color = 'Regular',   '#ff9f0a'
    elif score >= 40: level, color = 'Malo',      '#ff6b35'
    else:             level, color = 'Muy malo',  '#ff3b30'

    return {
        'score':   score,
        'level':   level,
        'color':   color,
        'total_h': round(total_h, 1),
        'details': [
            {'label': 'Duracion',   'pts': dur_pts,  'max': 40},
            {'label': 'Profundo+REM','pts': qual_pts, 'max': 35},
            {'label': 'Continuidad','pts': cont_pts, 'max': 15},
            {'label': 'Respiracion','pts': brth_pts, 'max': 10},
        ],
    }


def get_recovery_score(date_str: str) -> dict | None:
    """
    Puntuación de recuperación 0-100 basada en HRV, FC reposo y sueño.
    Algoritmo similar al Body Battery de Garmin.
    """
    if not DB_FILE.exists():
        return None

    # Valores del día
    hrv_today = _avg_numeric(date_str, 'HKQuantityTypeIdentifierHeartRateVariabilitySDNN')
    rhr_today = _avg_numeric(date_str, 'HKQuantityTypeIdentifierRestingHeartRate')
    sleep     = get_sleep_day(date_str)
    sleep_min = sleep.get('total_min', 0) if sleep else 0

    if not hrv_today and not rhr_today:
        return None

    # Línea base: media de los últimos 30 días
    dt = datetime.strptime(date_str, '%Y-%m-%d')
    d30 = (dt - timedelta(days=30)).strftime('%Y-%m-%d')

    with get_conn() as conn:
        hrv_base = conn.execute(
            'SELECT AVG(value) FROM records '
            'WHERE type=? AND date_day>=? AND date_day<? AND value IS NOT NULL',
            ('HKQuantityTypeIdentifierHeartRateVariabilitySDNN', d30, date_str)
        ).fetchone()[0]
        rhr_base = conn.execute(
            'SELECT AVG(value) FROM records '
            'WHERE type=? AND date_day>=? AND date_day<? AND value IS NOT NULL',
            ('HKQuantityTypeIdentifierRestingHeartRate', d30, date_str)
        ).fetchone()[0]

    if not hrv_base and not rhr_base:
        return None

    score = 50.0  # base

    # HRV: más alto = mejor recuperación (+/- 25 puntos)
    if hrv_today and hrv_base:
        hrv_ratio = hrv_today / hrv_base
        score += (hrv_ratio - 1) * 50  # ±25 puntos por ±50% de desviación

    # FC reposo: más baja = mejor (+/- 20 puntos)
    if rhr_today and rhr_base:
        rhr_ratio = rhr_today / rhr_base
        score -= (rhr_ratio - 1) * 40  # sube FC = baja score

    # Sueño: 7-9h = óptimo (+/- 20 puntos)
    if sleep_min:
        sleep_h = sleep_min / 60
        if sleep_h >= 7:
            score += min(20, (sleep_h - 7) * 10)
        else:
            score -= (7 - sleep_h) * 15

    score = max(0, min(100, round(score)))

    # Clasificación
    if score >= 80:
        label, color = 'Excelente', '#34c759'
    elif score >= 65:
        label, color = 'Buena', '#30b0c7'
    elif score >= 45:
        label, color = 'Normal', '#ff9500'
    elif score >= 25:
        label, color = 'Baja', '#ff6b3d'
    else:
        label, color = 'Muy baja', '#ff3b5c'

    return {
        'score': score,
        'label': label,
        'color': color,
        'hrv_today':  round(hrv_today, 1) if hrv_today else None,
        'hrv_base':   round(hrv_base,  1) if hrv_base  else None,
        'rhr_today':  round(rhr_today, 0) if rhr_today else None,
        'rhr_base':   round(rhr_base,  0) if rhr_base  else None,
        'sleep_h':    round(sleep_min / 60, 1) if sleep_min else None,
    }


def get_vo2_trend(date_str: str, days: int = 90) -> list[dict]:
    """VO₂ máx de los últimos N días."""
    if not DB_FILE.exists():
        return []
    dt     = datetime.strptime(date_str, '%Y-%m-%d')
    d_from = (dt - timedelta(days=days)).strftime('%Y-%m-%d')
    with get_conn() as conn:
        rows = conn.execute(
            'SELECT date_day, AVG(value) as v FROM records '
            'WHERE type=? AND date_day>=? AND date_day<=? AND value IS NOT NULL '
            'GROUP BY date_day ORDER BY date_day',
            ('HKQuantityTypeIdentifierVO2Max', d_from, date_str)
        ).fetchall()
    return [{'date': r['date_day'], 'v': round(r['v'], 1)} for r in rows]


# ── Histórico ─────────────────────────────────────────────────────────────────

def get_history_compare(metric: str, period: str) -> dict:
    """Devuelve datos del período actual Y del período anterior para comparativa."""
    current  = get_history(metric, period)
    previous = get_history(metric, period, offset=1)
    return {'current': current, 'previous': previous}


def get_history(metric: str, period: str, offset: int = 0) -> list[dict]:
    """
    Devuelve serie histórica agrupada por día/semana/mes.
    metric: 'steps'|'calories'|'distance'|'hr'|'rhr'|'hrv'|'sleep'|
            'weight'|'floors'|'resp'|'spo2'|'vo2'|'effort'|'daylight'
    period: 'week'|'month'|'year'|'all'
    """
    if not DB_FILE.exists():
        return []

    TYPES = {
        'steps':    ('HKQuantityTypeIdentifierStepCount',                 'sum'),
        'calories': ('HKQuantityTypeIdentifierActiveEnergyBurned',        'sum'),
        'distance': ('HKQuantityTypeIdentifierDistanceWalkingRunning',    'sum'),
        'hr':       ('HKQuantityTypeIdentifierHeartRate',                 'avg'),
        'rhr':      ('HKQuantityTypeIdentifierRestingHeartRate',          'avg'),
        'hrv':      ('HKQuantityTypeIdentifierHeartRateVariabilitySDNN',  'avg'),
        'sleep':    ('HKCategoryTypeIdentifierSleepAnalysis',             'sleep'),
        'weight':   ('HKQuantityTypeIdentifierBodyMass',                  'avg'),
        'floors':   ('HKQuantityTypeIdentifierFlightsClimbed',            'sum'),
        'resp':     ('HKQuantityTypeIdentifierRespiratoryRate',           'avg'),
        'spo2':     ('HKQuantityTypeIdentifierOxygenSaturation',         'avg'),
        'vo2':      ('HKQuantityTypeIdentifierVO2Max',                    'avg'),
        'effort':   ('HKQuantityTypeIdentifierPhysicalEffort',            'avg'),
        'daylight': ('HKQuantityTypeIdentifierTimeInDaylight',            'sum'),
    }

    if metric not in TYPES:
        return []

    hk_type, agg = TYPES[metric]

    from datetime import datetime, timedelta
    today = datetime.now().date()
    if period == 'week':
        since = (today - timedelta(days=7)).isoformat()
        group = 'day'
    elif period == 'month':
        since = (today - timedelta(days=30)).isoformat()
        group = 'day'
    elif period == 'year':
        since = (today - timedelta(days=365)).isoformat()
        group = 'week'
    else:  # all
        since = '2000-01-01'
        group = 'month'

    with get_conn() as conn:
        if agg == 'sleep':
            # Sueño: sumar minutos dormidos por día
            rows = conn.execute(
                "SELECT date_day, SUM("
                "  CASE WHEN (end_date - start_date) > 0 "
                "  THEN (julianday(substr(end_date,1,19)) - julianday(substr(start_date,1,19))) * 1440 "
                "  ELSE 0 END"
                ") as v FROM records "
                "WHERE type=? AND date_day>=? "
                "AND value_str NOT LIKE '%InBed%' "
                "AND value_str NOT LIKE '%Awake%' "
                "GROUP BY date_day ORDER BY date_day",
                (hk_type, since)
            ).fetchall()
            days = [{'date': r['date_day'], 'v': round(float(r['v'] or 0) / 60, 1)} for r in rows]
        elif agg == 'sum':
            rows = conn.execute(
                'SELECT date_day, SUM(value) as v FROM records '
                'WHERE type=? AND date_day>=? AND value IS NOT NULL '
                'GROUP BY date_day ORDER BY date_day',
                (hk_type, since)
            ).fetchall()
            days = [{'date': r['date_day'], 'v': round(float(r['v'] or 0), 1)} for r in rows]
        else:  # avg
            rows = conn.execute(
                'SELECT date_day, AVG(value) as v FROM records '
                'WHERE type=? AND date_day>=? AND value IS NOT NULL '
                'GROUP BY date_day ORDER BY date_day',
                (hk_type, since)
            ).fetchall()
            days = [{'date': r['date_day'], 'v': round(float(r['v'] or 0), 1)} for r in rows]

    if not days:
        return []

    if group == 'day':
        return days

    # Agrupar por semana o mes
    from collections import defaultdict
    buckets: dict = defaultdict(list)
    for d in days:
        dt = datetime.strptime(d['date'], '%Y-%m-%d')
        if group == 'week':
            key = dt.strftime('%Y-W%W')
            label = dt.strftime('%d %b')
        else:  # month
            key = dt.strftime('%Y-%m')
            label = dt.strftime('%b %Y')
        buckets[(key, label)].append(d['v'])

    result = []
    for (key, label), vals in sorted(buckets.items()):
        if agg == 'sum':
            v = round(sum(vals), 1)
        else:
            v = round(sum(vals) / len(vals), 1)
        result.append({'date': key, 'label': label, 'v': v})
    return result


# ── Histórico ──────────────────────────────────────────────────────────────────

def get_history_compare(metric: str, period: str) -> dict:
    """Devuelve datos del período actual Y del período anterior para comparativa."""
    current  = get_history(metric, period)
    previous = get_history(metric, period, offset=1)
    return {'current': current, 'previous': previous}


def get_history(metric: str, period: str, offset: int = 0) -> list[dict]:
    """
    Devuelve series históricas agrupadas por día/semana/mes.
    metric: 'pasos'|'calorias'|'distancia'|'fc'|'fc_reposo'|'hrv'|'spo2'|
            'sueno'|'peso'|'pisos'|'resp'|'esfuerzo'|'luz'
    period: 'week'|'month'|'year'|'all'
    """
    if not DB_FILE.exists():
        return []

    from datetime import datetime, timedelta

    TYPES = {
        'pasos':      ('HKQuantityTypeIdentifierStepCount',                   'sum'),
        'calorias':   ('HKQuantityTypeIdentifierActiveEnergyBurned',          'sum'),
        'distancia':  ('HKQuantityTypeIdentifierDistanceWalkingRunning',       'sum'),
        'fc':         ('HKQuantityTypeIdentifierHeartRate',                   'avg'),
        'fc_reposo':  ('HKQuantityTypeIdentifierRestingHeartRate',            'avg'),
        'hrv':        ('HKQuantityTypeIdentifierHeartRateVariabilitySDNN',    'avg'),
        'spo2':       ('HKQuantityTypeIdentifierOxygenSaturation',            'avg'),
        'sueno':      ('HKCategoryTypeIdentifierSleepAnalysis',               'sum'),
        'peso':       ('HKQuantityTypeIdentifierBodyMass',                    'avg'),
        'pisos':      ('HKQuantityTypeIdentifierFlightsClimbed',              'sum'),
        'resp':       ('HKQuantityTypeIdentifierRespiratoryRate',             'avg'),
        'esfuerzo':   ('HKQuantityTypeIdentifierPhysicalEffort',              'avg'),
        'luz':        ('HKQuantityTypeIdentifierTimeInDaylight',              'sum'),
        'vo2':        ('HKQuantityTypeIdentifierVO2Max',                      'avg'),
        'temp_muneca':   ('HKQuantityTypeIdentifierAppleSleepingWristTemperature','avg'),
        'ruido_auri':    ('HKQuantityTypeIdentifierHeadphoneAudioExposure',          'avg'),
        'ruido_env':     ('HKQuantityTypeIdentifierEnvironmentalAudioExposure',      'avg'),
        'alter_resp_sleep': ('HKQuantityTypeIdentifierAppleSleepingBreathingDisturbances', 'avg'),
        'mindful':          ('HKCategoryTypeIdentifierMindfulSession',                     'count'),
    }

    if metric not in TYPES:
        return []

    hk_type, agg = TYPES[metric]

    now = datetime.now()
    if offset > 0:
        if period == 'week':   now = now - timedelta(days=7*offset)
        elif period == 'month': now = now - timedelta(days=30*offset)
        elif period == 'year':  now = now - timedelta(days=365*offset)
        else: now = now - timedelta(days=365*offset)
    if period == 'week':
        date_from = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        group_by  = 'date_day'          # un punto por día
    elif period == 'month':
        date_from = (now - timedelta(days=30)).strftime('%Y-%m-%d')
        group_by  = 'date_day'
    elif period == 'year':
        date_from = (now - timedelta(days=365)).strftime('%Y-%m-%d')
        group_by  = "strftime('%Y-%W', date_day)"   # un punto por semana
    else:  # all
        date_from = '2000-01-01'
        group_by  = "strftime('%Y-%m', date_day)"   # un punto por mes

    date_to = now.strftime('%Y-%m-%d')

    # Mindfulness: calcular minutos totales por día (no count)
    if metric == 'mindful':
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT date_day, substr(start_date,1,19) as s, substr(end_date,1,19) as e "
                "FROM records WHERE type='HKCategoryTypeIdentifierMindfulSession' "
                "AND date_day>=? AND date_day<=? ORDER BY date_day",
                (date_from, date_to)
            ).fetchall()
        from collections import defaultdict as _dd
        from datetime import datetime as _dtt
        daily = _dd(float)
        for r in rows:
            try:
                s = _dtt.strptime(r['s'], '%Y-%m-%d %H:%M:%S')
                e = _dtt.strptime(r['e'], '%Y-%m-%d %H:%M:%S')
                daily[r['date_day']] += (e-s).total_seconds()/60
            except Exception:
                pass
        raw = [{'date': k, 'v': round(v, 1)} for k, v in sorted(daily.items())]
        if period in ('year','all'):
            fmt = '%Y-%W' if period == 'year' else '%Y-%m'
            from collections import defaultdict as _dd2
            from datetime import datetime as _dtt2
            grouped = _dd2(list)
            for item in raw:
                try:
                    key = _dtt2.strptime(item['date'],'%Y-%m-%d').strftime(fmt)
                    grouped[key].append(item['v'])
                except Exception:
                    pass
            return [{'date': k, 'v': round(sum(vs),1)} for k, vs in sorted(grouped.items())]
        return raw

    # Sueño: contar sólo minutos dormidos (no InBed)
    if metric == 'sueno':
        # Calcular duración en Python para evitar problemas con zona horaria en SQLite
        from datetime import datetime as _dt, timedelta as _td
        from collections import defaultdict

        try:
            d_from_ext = (_dt.strptime(date_from,'%Y-%m-%d') - _td(days=1)).strftime('%Y-%m-%d')
        except Exception:
            d_from_ext = date_from

        with get_conn() as conn:
            rows = conn.execute(
                'SELECT substr(start_date,1,19) as s, substr(end_date,1,19) as e, '
                'substr(end_date,1,10) as g '
                'FROM records '
                'WHERE type=? AND date_day>=? AND date_day<=? '
                "AND value_str NOT LIKE '%InBed%' "
                "AND value_str NOT LIKE '%Awake%' "
                'ORDER BY start_date',
                (hk_type, d_from_ext, date_to)
            ).fetchall()

        # Calcular minutos en Python
        daily = defaultdict(float)
        for r in rows:
            try:
                s = _dt.strptime(r['s'], '%Y-%m-%d %H:%M:%S')
                e = _dt.strptime(r['e'], '%Y-%m-%d %H:%M:%S')
                mins = (e - s).total_seconds() / 60
                if mins > 0:
                    daily[r['g']] += mins
            except Exception:
                pass

        # Filtrar siestas cortas — solo sueño nocturno principal (>3h)
        daily = {k: v for k, v in daily.items() if v > 180}

        if period in ('year', 'all'):
            fmt = '%Y-%W' if period == 'year' else '%Y-%m'
            grouped = defaultdict(list)
            for date_str, mins in daily.items():
                try:
                    key = _dt.strptime(date_str, '%Y-%m-%d').strftime(fmt)
                    grouped[key].append(mins / 60)
                except Exception:
                    pass
            return [{'date': k, 'v': round(sum(vs)/len(vs), 2)} for k, vs in sorted(grouped.items())]

        return [{'date': k, 'v': round(v/60, 2)} for k, v in sorted(daily.items())]

    agg_fn = 'SUM(value)' if agg == 'sum' else 'AVG(value)'

    with get_conn() as conn:
        rows = conn.execute(f"""
            SELECT {group_by} as g, {agg_fn} as v
            FROM records
            WHERE type = ?
              AND date_day >= ? AND date_day <= ?
              AND value IS NOT NULL
            GROUP BY g ORDER BY g
        """, (hk_type, date_from, date_to)).fetchall()
        # Peso: si no hay datos en el período, coger el último valor conocido
        if metric == 'peso' and not rows:
            last = conn.execute(
                'SELECT date_day as g, AVG(value) as v FROM records '
                'WHERE type=? AND value IS NOT NULL '
                'ORDER BY date_day DESC LIMIT 1', (hk_type,)
            ).fetchone()
            if last and last['v']:
                rows = [last]

    mult = 1
    if metric == 'distancia':  mult = 0.001   # m → km
    if metric == 'spo2':       mult = 100      # 0-1 → %

    results = []
    for r in rows:
        if r['v'] is None: continue
        v = round(r['v'] * mult, 2)
        # Umbrales mínimos por métrica para excluir ruido
        min_threshold = 0.5 if metric == 'distancia' else 0.01
        if v < min_threshold: continue
        results.append({'date': r['g'], 'v': v})
    return results
