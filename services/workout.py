"""
services/workout.py
Lee entrenamientos del export.xml y sus rutas GPX del export.zip.
"""

import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timedelta

UPLOAD_DIR = Path('uploads')
ZIP_PATH   = UPLOAD_DIR / 'export.zip'

GPX_NS = 'http://www.topografix.com/GPX/1/1'

# Caché en memoria — se invalida al reimportar
_WORKOUT_CACHE: list[dict] | None = None

WORKOUT_NAMES = {
    'HKWorkoutActivityTypeRunning':            ('Carrera',       '🏃'),
    'HKWorkoutActivityTypeWalking':            ('Caminar',       '🚶'),
    'HKWorkoutActivityTypeCycling':            ('Ciclismo',      '🚴'),
    'HKWorkoutActivityTypeSwimming':           ('Natación',      '🏊'),
    'HKWorkoutActivityTypeHiking':             ('Senderismo',    '🥾'),
    'HKWorkoutActivityTypeYoga':               ('Yoga',          '🧘'),
    'HKWorkoutActivityTypeFunctionalStrengthTraining': ('Fuerza', '💪'),
    'HKWorkoutActivityTypeTraditionalStrengthTraining':('Fuerza', '💪'),
    'HKWorkoutActivityTypeHighIntensityIntervalTraining': ('HIIT','⚡'),
    'HKWorkoutActivityTypeSoccer':             ('Fútbol',        '⚽'),
    'HKWorkoutActivityTypeBasketball':         ('Baloncesto',    '🏀'),
    'HKWorkoutActivityTypeTennis':             ('Tenis',         '🎾'),
    'HKWorkoutActivityTypeDance':              ('Baile',         '💃'),
    'HKWorkoutActivityTypeElliptical':         ('Elíptica',      '🔄'),
    'HKWorkoutActivityTypeRowing':             ('Remo',          '🚣'),
    'HKWorkoutActivityTypeSki':                ('Esquí',         '⛷️'),
    'HKWorkoutActivityTypeSnowboarding':       ('Snowboard',     '🏂'),
    'HKWorkoutActivityTypeCrossTraining':      ('Entrenamiento', '🏋️'),
    'HKWorkoutActivityTypeMindAndBody':        ('Mente y cuerpo','🧠'),
    'HKWorkoutActivityTypeOther':              ('Otro',          '🏅'),
}


def _parse_dt(s: str) -> datetime | None:
    for fmt in ('%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%d %H:%M:%S %z', '%Y-%m-%d %H:%M:%S'):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def _fmt_duration(minutes: float) -> str:
    h = int(minutes // 60)
    m = int(minutes % 60)
    s = int((minutes * 60) % 60)
    if h > 0:
        return f'{h}h {m:02d}m'
    return f'{m}m {s:02d}s'


def _parse_gpx(content: str) -> list[dict]:
    """Parsea un GPX y devuelve lista de puntos {lat, lon, ele, time, speed}."""
    points = []
    try:
        root = ET.fromstring(content)
        ns   = {'g': GPX_NS}
        for trkpt in root.findall('.//g:trkpt', ns):
            lat = float(trkpt.get('lat', 0))
            lon = float(trkpt.get('lon', 0))
            ele_el = trkpt.find('g:ele', ns)
            time_el = trkpt.find('g:time', ns)
            spd_el  = trkpt.find('g:extensions/g:speed', ns)
            if spd_el is None:
                spd_el = trkpt.find('.//g:speed', ns)
                if spd_el is None:
                    # Intentar sin namespace en extensions
                    for ext_child in trkpt.findall('.//{*}speed'):
                        spd_el = ext_child; break
                    # Sin namespace
                    if spd_el is None:
                        ext = trkpt.find('g:extensions', ns)
                        if ext is not None:
                            for ch in ext:
                                if 'speed' in ch.tag.lower():
                                    spd_el = ch; break
            points.append({
                'lat':   lat,
                'lon':   lon,
                'ele':   float(ele_el.text) if ele_el is not None else None,
                'time':  time_el.text if time_el is not None else None,
                'speed': float(spd_el.text) * 3.6 if spd_el is not None else None,  # m/s → km/h
            })
    except Exception as e:
        pass
    return points


def _gpx_filename_from_date(start_date: str) -> str | None:
    """Intenta adivinar el nombre del fichero GPX a partir de la fecha de inicio."""
    dt = _parse_dt(start_date)
    if not dt:
        return None
    # Ajustar a hora local (los ficheros GPX usan hora local en el nombre)
    # Formato: route_YYYY-MM-DD_H.MMam/pm
    # Generar variaciones posibles (±1h por zona horaria)
    candidates = []
    for delta in range(-2, 3):
        d = dt + timedelta(hours=delta)
        hour = d.hour
        minute = d.minute
        ampm = 'am' if hour < 12 else 'pm'
        hour12 = hour % 12 or 12
        candidates.append(f"route_{d.strftime('%Y-%m-%d')}_{hour12}.{minute:02d}{ampm}.gpx")
    return candidates


def invalidate_workout_cache() -> None:
    global _WORKOUT_CACHE
    _WORKOUT_CACHE = None


def list_workouts() -> list[dict]:
    """
    Lista todos los entrenamientos del export.xml con metadatos.
    Usa caché en memoria — se invalida al reimportar.
    """
    global _WORKOUT_CACHE
    if _WORKOUT_CACHE is not None:
        return _WORKOUT_CACHE

    if not ZIP_PATH.exists():
        return []

    workouts = []

    with zipfile.ZipFile(ZIP_PATH) as zf:
        # Índice de ficheros GPX disponibles
        gpx_names_available = {
            n.split('/')[-1]: n
            for n in zf.namelist()
            if n.endswith('.gpx')
        }

        xml_name = next((n for n in zf.namelist() if n.endswith('export.xml')), None)
        if not xml_name:
            return []

        # Leer el XML línea a línea y extraer bloques <Workout>…</Workout>
        # completos para parsear cada uno preservando los hijos
        with zf.open(xml_name) as f:
            in_workout = False
            buf = []
            for raw_line in f:
                line = raw_line.decode('utf-8', errors='replace')
                if '<Workout ' in line and not in_workout:
                    in_workout = True
                    buf = [line]
                elif in_workout:
                    buf.append(line)
                    if '</Workout>' in line:
                        in_workout = False
                        xml_str = ''.join(buf)
                        try:
                            elem = ET.fromstring(xml_str)
                        except ET.ParseError:
                            buf = []
                            continue

                        w_type     = elem.get('workoutActivityType', '')
                        start_date = elem.get('startDate', '')
                        end_date   = elem.get('endDate', '')
                        duration   = float(elem.get('duration', 0))
                        source     = elem.get('sourceName', '')

                        # Estadísticas — ahora los atributos están completos
                        stats    = {}
                        gpx_file = None
                        for child in elem:
                            if child.tag == 'WorkoutStatistics':
                                t    = child.get('type', '')
                                unit = child.get('unit', '')
                                v    = child.get('sum') or child.get('average') or                                        child.get('minimum') or child.get('maximum')
                                if t and v is not None:
                                    val = float(v)
                                    # Distancia: convertir m→km si unidad es m
                                    if 'Distance' in t and unit in ('m', 'meter', 'meters'):
                                        val = val / 1000
                                    stats[t] = val
                            elif child.tag == 'WorkoutRoute':
                                for link in child:
                                    if link.tag == 'FileReference':
                                        # Intentar matching con GPX
                                        ref = link.get('path', '')
                                        fname = ref.split('/')[-1]
                                        if fname in gpx_names_available:
                                            gpx_file = gpx_names_available[fname]

                        # Si no hubo FileReference, intentar por fecha
                        if gpx_file is None:
                            for c in (_gpx_filename_from_date(start_date) or []):
                                if c in gpx_names_available:
                                    gpx_file = gpx_names_available[c]
                                    break

                        dist_km = stats.get('HKQuantityTypeIdentifierDistanceWalkingRunning',
                                  stats.get('HKQuantityTypeIdentifierDistanceCycling',
                                  stats.get('HKQuantityTypeIdentifierDistanceSwimming', 0)))
                        kcal    = stats.get('HKQuantityTypeIdentifierActiveEnergyBurned', 0)

                        name, icon = WORKOUT_NAMES.get(w_type, ('Entrenamiento', '🏅'))
                        dt         = _parse_dt(start_date)

                        workouts.append({
                            'type':         w_type,
                            'name':         name,
                            'icon':         icon,
                            'date':         dt.strftime('%Y-%m-%d') if dt else start_date[:10],
                            'time':         dt.strftime('%H:%M') if dt else '',
                            'start':        start_date,
                            'end':          end_date,
                            'duration_min': round(duration, 1),
                            'duration_fmt': _fmt_duration(duration),
                            'dist_km':      round(dist_km, 2),
                            'kcal':         round(kcal),
                            'source':       source,
                            'has_route':    gpx_file is not None,
                            'gpx_file':     gpx_file,
                        })
                        buf = []

    workouts.sort(key=lambda w: w['start'], reverse=True)
    _WORKOUT_CACHE = workouts
    return workouts


def get_workout_route(gpx_path: str) -> dict | None:
    """Lee un fichero GPX del ZIP y devuelve los puntos de la ruta."""
    if not ZIP_PATH.exists():
        return None

    with zipfile.ZipFile(ZIP_PATH) as zf:
        matches = [n for n in zf.namelist() if n == gpx_path or n.endswith('/' + gpx_path.split('/')[-1])]
        if not matches:
            return None
        with zf.open(matches[0]) as f:
            content = f.read().decode('utf-8', errors='replace')

    points = _parse_gpx(content)
    if not points:
        return None

    # Calcular stats de la ruta
    speeds  = [p['speed'] for p in points if p['speed'] is not None]
    eles    = [p['ele']   for p in points if p['ele']   is not None]

    # Distancia total aproximada (Haversine simplificado)
    import math
    dist_km = 0.0
    for i in range(1, len(points)):
        p1, p2 = points[i-1], points[i]
        dlat = math.radians(p2['lat'] - p1['lat'])
        dlon = math.radians(p2['lon'] - p1['lon'])
        a = math.sin(dlat/2)**2 + math.cos(math.radians(p1['lat'])) * \
            math.cos(math.radians(p2['lat'])) * math.sin(dlon/2)**2
        dist_km += 6371 * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

    return {
        'points':    points,
        'n_points':  len(points),
        'dist_km':   round(dist_km, 2),
        'speed_avg': round(sum(speeds)/len(speeds), 1) if speeds else None,
        'speed_max': round(max(speeds), 1)             if speeds else None,
        'ele_min':   round(min(eles), 0)               if eles   else None,
        'ele_max':   round(max(eles), 0)               if eles   else None,
        'ele_gain':  round(sum(max(0, eles[i]-eles[i-1]) for i in range(1,len(eles))), 0) if eles else None,
    }
